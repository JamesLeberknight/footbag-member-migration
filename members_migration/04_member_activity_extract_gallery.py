#!/usr/bin/env python3
"""
Stage 1B: Extract activity evidence from gallery pages in the local mirror.

Inputs:
  mirror_out/www.footbag.org/gallery/show/.../index.html

Outputs:
  out/members/stage1_member_activity_raw.csv

Deterministic; public mirror only; does NOT guess identities.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from pathlib import Path
from typing import Dict, List

from bs4 import BeautifulSoup


RE_GALLERY_SHOW = re.compile(r"(?:^|/)gallery/show/(\d+)/index\.html$", re.I)
RE_MEMBER_PROFILE_LINK = re.compile(r"(?:https?://www\.footbag\.org)?/members/profile/(\d+)", re.I)

# Loose text signals (used only for name-only evidence rows)
RE_CREDIT_LINE = re.compile(r"\bcredit\b|\bcredited\b|\bphoto by\b|\bvideo by\b", re.I)
RE_UPLOADER_LINE = re.compile(r"\bupload(ed|er)?\b|\bsubmitted\b", re.I)
RE_AUTHOR_LINE = re.compile(r"\bposted by\b|\bauthor\b", re.I)


def clean_text(s: str) -> str:
    s = s.replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def stable_id(parts: List[str]) -> str:
    h = hashlib.sha1(("||".join(parts)).encode("utf-8")).hexdigest()
    return h


def derive_source_url(rel_path: str) -> str:
    rel = rel_path.replace("\\", "/")
    rel = re.sub(r"/index\.html$", "", rel)
    return f"http://www.footbag.org/{rel}"


def extract_evidence_from_gallery_page(rel_path: str, html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")

    # Collect linked member ids
    linked_ids = set()
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip().strip('"').strip("'")
        m = RE_MEMBER_PROFILE_LINK.search(href)
        if m:
            linked_ids.add(m.group(1))

    out: List[Dict[str, str]] = []
    source_url = derive_source_url(rel_path)

    def emit(
        evidence_type: str,
        legacy_member_id: str,
        evidence_name_text: str,
        link_target: str,
        confidence: str,
        context: str,
    ):
        eid = stable_id([evidence_type, legacy_member_id or "", evidence_name_text or "", rel_path, context])
        out.append(
            {
                "evidence_id": eid,
                "evidence_type": evidence_type,
                "legacy_member_id": legacy_member_id,
                "legacy_username": "",
                "evidence_name_text": evidence_name_text,
                "evidence_date_raw": "",
                "source_path": rel_path,
                "source_url": source_url,
                "link_target": link_target,
                "context_text": context,
                "confidence": confidence,
                "privacy_flag": "public",
            }
        )

    # HIGH confidence evidence: any explicit member profile link on gallery page
    for mid in sorted(linked_ids, key=lambda x: int(x) if x.isdigit() else x):
        emit(
            evidence_type="gallery_presence",
            legacy_member_id=mid,
            evidence_name_text="",
            link_target=f"/members/profile/{mid}",
            confidence="high",
            context="linked_member_profile",
        )

    # LOW confidence evidence: if page contains explicit credit/uploader/author keywords
    # We do not attach to a member_id unless a link exists.
    # Keep text-only evidence for human review.
    for el in soup.find_all(["div", "td", "p", "span", "li"]):
        t = clean_text(el.get_text(" ", strip=True))
        if not t or len(t) > 300:
            continue

        etype = None
        if RE_CREDIT_LINE.search(t):
            etype = "gallery_credit_text"
        elif RE_UPLOADER_LINE.search(t):
            etype = "gallery_uploader_text"
        elif RE_AUTHOR_LINE.search(t):
            etype = "gallery_author_text"

        if etype:
            emit(
                evidence_type=etype,
                legacy_member_id="",
                evidence_name_text=t,
                link_target="",
                confidence="low",
                context=t,
            )

    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mirror-root", default="mirror_out/www.footbag.org")
    ap.add_argument("--out", default="out/members/stage1_member_activity_raw.csv")
    ap.add_argument("--limit", type=int, default=0, help="0 = no limit")
    args = ap.parse_args()

    root = Path(args.mirror_root)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    gallery_pages = []
    for p in root.rglob("*.html"):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root)).replace("\\", "/")
        if RE_GALLERY_SHOW.search(rel):
            gallery_pages.append((rel, p))

    gallery_pages.sort(key=lambda x: x[0])
    if args.limit and args.limit > 0:
        gallery_pages = gallery_pages[: args.limit]

    rows: List[Dict[str, str]] = []
    for rel, p in gallery_pages:
        html = p.read_text(encoding="utf-8", errors="replace")
        rows.extend(extract_evidence_from_gallery_page(rel, html))

    rows.sort(key=lambda r: (r["evidence_type"], r["legacy_member_id"], r["source_path"], r["evidence_id"]))

    cols = [
        "evidence_id",
        "evidence_type",
        "legacy_member_id",
        "legacy_username",
        "evidence_name_text",
        "evidence_date_raw",
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

    print(f"Wrote {len(rows)} evidence rows from {len(gallery_pages)} gallery pages -> {out_path}")


if __name__ == "__main__":
    main()
