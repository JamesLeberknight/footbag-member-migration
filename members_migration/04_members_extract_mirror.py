#!/usr/bin/env python3
"""
Stage 1: Extract raw member profile data from local mirror.

Input:
  mirror_out/www.footbag.org/.../members/profile/<id>/index.html

Output:
  out/members/stage1_members_raw.csv

Notes:
- Public mirror only. No live scraping.
- Deterministic.
- Provenance preserved via source_path.
- Privacy-aware: emails/phones/addresses go to pii_* columns.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup


RE_MEMBER_PROFILE_PATH = re.compile(r"(?:^|/)members/profile/(\d+)/index\.html$", re.I)
RE_TITLE_PROFILE_FOR = re.compile(r"member profile for\s+([^\s<]+)", re.I)
RE_LAST_LOGIN = re.compile(r"Last Login:\s*(.+)$", re.I)
RE_JOINED = re.compile(r"\bJoined:\s*([0-9]{2}/[0-9]{2}/[0-9]{2,4})\b", re.I)
RE_VALIDATED = re.compile(r"last validated:\s*([0-9]{2}/[0-9]{2}/[0-9]{2,4})", re.I)
RE_CLUB_SHOW = re.compile(r"/clubs/show/([^/?#]+)", re.I)
RE_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
RE_PHONE = re.compile(r"(\+?\d[\d\-\(\) ]{7,}\d)")
RE_ADDR_HINT = re.compile(r"\b(address|street|st\.|road|rd\.|ave|avenue|zip|postal)\b", re.I)


def clean_text(s: str) -> str:
    s = s.replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_legacy_username(soup: BeautifulSoup) -> str:
    candidates = []
    if soup.title and soup.title.string:
        candidates.append(clean_text(soup.title.string))
    h1 = soup.find("h1")
    if h1:
        candidates.append(clean_text(h1.get_text(" ", strip=True)))
    for c in candidates:
        m = RE_TITLE_PROFILE_FOR.search(c)
        if m:
            return clean_text(m.group(1))
    return ""


def extract_label_value_pairs(soup: BeautifulSoup) -> Dict[str, str]:
    """
    Heuristic extraction for pages formatted like:
      <b>Country:</b> USA
    or table rows like:
      <tr><td>Country</td><td>USA</td></tr>

    We return a lowercase key -> value mapping (raw strings).
    """
    out: Dict[str, str] = {}

    # Table-based extraction
    for tr in soup.find_all("tr"):
        tds = tr.find_all(["td", "th"])
        if len(tds) == 2:
            k = clean_text(tds[0].get_text(" ", strip=True)).strip(":").lower()
            v = clean_text(tds[1].get_text(" ", strip=True))
            if k and v and len(k) <= 40:
                out[k] = v

    # Bold-label extraction
    for b in soup.find_all(["b", "strong"]):
        k = clean_text(b.get_text(" ", strip=True)).strip(":").lower()
        if not k or len(k) > 40:
            continue
        # try to get the text immediately after
        nxt = b.next_sibling
        if nxt:
            v = clean_text(str(nxt)) if isinstance(nxt, str) else clean_text(nxt.get_text(" ", strip=True))
            v = v.lstrip(":").strip()
            if v:
                out.setdefault(k, v)

    return out


def extract_profile_structured(soup: BeautifulSoup) -> Dict[str, str]:
    """
    Extracts fields using known Footbag members.css structure.
    Returns raw strings; empty if not present.
    """
    out: Dict[str, str] = {}

    # Real name
    name_el = soup.select_one("div.membersProfileName")
    if name_el:
        out["name_display"] = clean_text(name_el.get_text(" ", strip=True))

    # Last login (optional / semi-sensitive)
    ll_el = soup.select_one("div.membersProfileLogin")
    if ll_el:
        t = clean_text(ll_el.get_text(" ", strip=True))
        m = RE_LAST_LOGIN.search(t)
        out["last_login_raw"] = clean_text(m.group(1)) if m else t

    # Joined date (often in <dd>)
    joined = ""
    for dd in soup.find_all("dd"):
        t = clean_text(dd.get_text(" ", strip=True))
        m = RE_JOINED.search(t)
        if m:
            joined = m.group(1)
            break
    if joined:
        out["joined_raw"] = joined

    # My Club section
    # We look for <h2>My Club:</h2> then scan following links until next h2/h3
    club_ids = []
    club_names = []
    club_validated = ""

    h2s = soup.find_all(["h2", "h3"])
    for h in h2s:
        ht = clean_text(h.get_text(" ", strip=True)).lower()
        if ht.startswith("my club"):
            # walk forward siblings until next header
            cur = h
            for _ in range(200):
                cur = cur.find_next_sibling()
                if cur is None:
                    break
                if cur.name in ("h2", "h3"):
                    break
                # links to clubs
                for a in cur.find_all("a"):
                    href = (a.get("href") or "").strip()
                    m = RE_CLUB_SHOW.search(href)
                    if m:
                        club_ids.append(m.group(1))
                        club_names.append(clean_text(a.get_text(" ", strip=True)))
                # validated date text
                t = clean_text(cur.get_text(" ", strip=True))
                m = RE_VALIDATED.search(t)
                if m:
                    club_validated = m.group(1)
            break

    if club_ids:
        out["club_ids"] = ";".join(dict.fromkeys(club_ids))  # dedupe preserve order
    if club_names:
        out["club_names"] = ";".join(dict.fromkeys(club_names))
    if club_validated:
        out["club_last_validated_raw"] = club_validated

    return out


def detect_photo(soup: BeautifulSoup) -> bool:
    # crude but useful: any image on the page that looks like profile image
    for img in soup.find_all("img"):
        src = (img.get("src") or "").lower()
        if "members" in src or "profile" in src or "user" in src or "avatar" in src:
            return True
    # fallback: any image at all
    return bool(soup.find("img"))


def extract_pii(text: str) -> Tuple[str, str, str]:
    emails = sorted(set(RE_EMAIL.findall(text)))
    phones = sorted(set(m.group(1) for m in RE_PHONE.finditer(text)))
    addr = ""
    if RE_ADDR_HINT.search(text):
        addr = "POSSIBLE_ADDRESS_HINT_PRESENT"
    return (";".join(emails), ";".join(phones), addr)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mirror-root", default="mirror_out/www.footbag.org")
    ap.add_argument("--out", default="out/members/stage1_members_raw.csv")
    args = ap.parse_args()

    root = Path(args.mirror_root)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    html_files = sorted(p for p in root.rglob("*.html") if p.is_file())

    rows: List[Dict[str, str]] = []

    for p in html_files:
        rel = str(p.relative_to(root)).replace("\\", "/")
        m = RE_MEMBER_PROFILE_PATH.search(rel)
        if not m:
            continue

        legacy_id = m.group(1)
        html = p.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")

        profile_container = soup.select_one("div.membersProfileNameplate") or soup
        profile_text = clean_text(profile_container.get_text(" ", strip=True))
        pii_email, pii_phone, pii_addr = extract_pii(profile_text)

        legacy_username = extract_legacy_username(soup)

        structured = extract_profile_structured(soup)
        name_display = structured.get("name_display", "")
        joined_raw = structured.get("joined_raw", "")
        last_login_raw = structured.get("last_login_raw", "")
        club_ids = structured.get("club_ids", "")
        club_names = structured.get("club_names", "")
        club_last_validated_raw = structured.get("club_last_validated_raw", "")

        # Fallback: label/value pairs from generic structure
        fields = extract_label_value_pairs(soup)

        # Common field keys vary; we map conservatively
        def pick(*keys: str) -> str:
            for k in keys:
                if k in fields:
                    return fields[k]
            return ""

        nickname = pick("nickname", "nick", "handle")
        country = pick("country", "nation")
        state_region = pick("state", "region", "province")
        city = pick("city", "town")
        club_text = pick("club", "club(s)", "clubs", "club affiliation")
        member_since = pick("member since", "since", "joined", "member since:")

        # Bio: try common containers, else empty
        bio_raw = ""
        for sel in ["div.bio", "div.profile", "div.content", "td"]:
            el = soup.select_one(sel)
            if el:
                t = clean_text(el.get_text(" ", strip=True))
                if t and len(t) > 80:
                    bio_raw = t[:2000]
                    break

        has_photo = "1" if detect_photo(soup) else "0"

        # Parse confidence
        conf = "high" if name_display else "medium"
        if not name_display and legacy_username:
            conf = "medium"
        if not name_display and not legacy_username and not fields:
            conf = "low"

        row = {
            "legacy_member_id": legacy_id,
            "legacy_username": legacy_username,
            "profile_url": f"http://www.footbag.org/members/profile/{legacy_id}",
            "name_display": name_display,
            "joined_raw": joined_raw,
            "last_login_raw": last_login_raw,
            "nickname": nickname,
            "country": country,
            "state_region": state_region,
            "city": city,
            "club_text": club_text,
            "club_ids": club_ids,
            "club_names": club_names,
            "club_last_validated_raw": club_last_validated_raw,
            "member_since": member_since,
            "bio_raw": bio_raw,
            "has_photo": has_photo,
            "pii_email_raw": pii_email,
            "pii_phone_raw": pii_phone,
            "pii_address_raw": pii_addr,
            "source_path": rel,
            "parse_confidence": conf,
            "notes": "",
        }
        rows.append(row)

    # Deterministic sort
    rows.sort(key=lambda r: int(r["legacy_member_id"]))

    cols = [
        "legacy_member_id",
        "legacy_username",
        "profile_url",
        "name_display",
        "joined_raw",
        "last_login_raw",
        "nickname",
        "country",
        "state_region",
        "city",
        "club_text",
        "club_ids",
        "club_names",
        "club_last_validated_raw",
        "member_since",
        "bio_raw",
        "has_photo",
        "pii_email_raw",
        "pii_phone_raw",
        "pii_address_raw",
        "source_path",
        "parse_confidence",
        "notes",
    ]

    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f"Wrote {len(rows)} rows -> {out_path}")


if __name__ == "__main__":
    main()
