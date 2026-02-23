#!/usr/bin/env python3
"""
Stage 1C: Extract activity evidence from event pages in the local mirror.

Focus:
- Extract role-linked evidence (especially "Contact:") from /events/show/<event_id>/ pages.
- Also captures any other /members/profile/<id> links found on the page.
- Deterministic and provenance-preserving.

Input:
  mirror_out/www.footbag.org/events/show/<event_id>/index.html

Output:
  out/members/stage1_member_activity_events.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from pathlib import Path
from typing import Dict, List, Optional

from bs4 import BeautifulSoup


RE_EVENT_SHOW = re.compile(r"(?:^|/)events/show/(\d+)/index\.html$", re.I)
RE_MEMBER_PROFILE_LINK = re.compile(r"(?:https?://www\.footbag\.org)?/members/profile/(\d+)", re.I)

# Recognize role labels nearby links
ROLE_WORDS = re.compile(r"\b(contact|director|organizer|hosted by|host|judge|sponsor|officer)\b", re.I)

# Loose date capture (for event_date_raw); safe to keep raw
RE_DATEISH = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})\b")


def clean_text(s: str) -> str:
    s = s.replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def stable_id(parts: List[str]) -> str:
    return hashlib.sha1(("||".join(parts)).encode("utf-8")).hexdigest()


def derive_source_url(rel_path: str) -> str:
    rel = rel_path.replace("\\", "/")
    rel = re.sub(r"/index\.html$", "", rel)
    return f"http://www.footbag.org/{rel}"


def extract_event_title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        t = clean_text(h1.get_text(" ", strip=True))
        if t:
            return t
    if soup.title and soup.title.string:
        return clean_text(soup.title.string)
    return ""


def find_candidate_date(text: str) -> str:
    m = RE_DATEISH.search(text)
    return m.group(1) if m else ""


def infer_role_context(a) -> str:
    """
    Try to capture role label context for a member link.
    In your HTML, role label like:
      <div class="name">Contact:</div>
    appears near the <a href=/members/profile/...> element.

    We build a small context window from:
    - nearest dt/dd/li/p/div ancestor
    - previous siblings of that ancestor
    """
    # nearest container
    container = a.find_parent(["dt", "dd", "li", "p", "div", "td"])
    parts: List[str] = []

    if container:
        parts.append(clean_text(container.get_text(" ", strip=True))[:240])

        # look at a couple of previous siblings where "Contact:" might be
        prev = container.find_previous_sibling()
        if prev:
            parts.append(clean_text(prev.get_text(" ", strip=True))[:240])
            prev2 = prev.find_previous_sibling()
            if prev2:
                parts.append(clean_text(prev2.get_text(" ", strip=True))[:240])

    # fallback: parent text
    if not parts and a.parent:
        parts.append(clean_text(a.parent.get_text(" ", strip=True))[:240])

    ctx = " | ".join([p for p in parts if p])
    return ctx[:240]


def extract_evidence_from_event_page(rel_path: str, html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    source_url = derive_source_url(rel_path)

    m = RE_EVENT_SHOW.search(rel_path)
    event_id = m.group(1) if m else ""

    event_title = extract_event_title(soup)
    page_text = clean_text(soup.get_text(" ", strip=True))
    event_date_raw = find_candidate_date(page_text)

    rows: List[Dict[str, str]] = []

    def emit(evidence_type: str, legacy_member_id: str, evidence_name_text: str, link_target: str, confidence: str, context: str):
        eid = stable_id([evidence_type, legacy_member_id or "", evidence_name_text or "", rel_path, context])
        rows.append({
            "evidence_id": eid,
            "evidence_type": evidence_type,
            "legacy_member_id": legacy_member_id,
            "legacy_username": "",
            "evidence_name_text": evidence_name_text,
            "event_id": event_id,
            "event_title": event_title,
            "event_date_raw": event_date_raw,
            "source_path": rel_path,
            "source_url": source_url,
            "link_target": link_target,
            "context_text": context,
            "confidence": confidence,
            "privacy_flag": "public",
        })

    # Extract all member profile links on the page
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip().strip('"').strip("'")
        mm = RE_MEMBER_PROFILE_LINK.search(href)
        if not mm:
            continue

        mid = mm.group(1)
        link_text = clean_text(a.get_text(" ", strip=True))
        context = infer_role_context(a)

        # Classify role vs participant/other based on context
        ctx_low = context.lower()
        if "contact" in ctx_low:
            etype = "event_role_contact_link"
        elif ROLE_WORDS.search(context):
            etype = "event_role_link"
        else:
            etype = "event_member_link"

        emit(
            evidence_type=etype,
            legacy_member_id=mid,
            evidence_name_text=link_text,
            link_target=f"/members/profile/{mid}",
            confidence="high",
            context=context or link_text,
        )

    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mirror-root", default="mirror_out/www.footbag.org")
    ap.add_argument("--out", default="out/members/stage1_member_activity_events.csv")
    ap.add_argument("--limit", type=int, default=0, help="0 = no limit")
    args = ap.parse_args()

    root = Path(args.mirror_root)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    event_pages = []
    for p in root.rglob("*.html"):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root)).replace("\\", "/")
        if RE_EVENT_SHOW.search(rel):
            event_pages.append((rel, p))

    event_pages.sort(key=lambda x: x[0])
    if args.limit and args.limit > 0:
        event_pages = event_pages[: args.limit]

    rows: List[Dict[str, str]] = []
    for rel, p in event_pages:
        html = p.read_text(encoding="utf-8", errors="replace")
        rows.extend(extract_evidence_from_event_page(rel, html))

    # Deterministic output ordering
    rows.sort(key=lambda r: (r["evidence_type"], r["legacy_member_id"], r["event_id"], r["source_path"], r["evidence_id"]))

    cols = [
        "evidence_id",
        "evidence_type",
        "legacy_member_id",
        "legacy_username",
        "evidence_name_text",
        "event_id",
        "event_title",
        "event_date_raw",
        "source_path",
        "source_url",
        "link_target",
        "context_text",
        "confidence",
        "privacy_flag",
    ]

    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f"Wrote {len(rows)} evidence rows from {len(event_pages)} event pages -> {out_path}")


if __name__ == "__main__":
    main()
