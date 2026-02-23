#!/usr/bin/env python3
"""
Phase 0 Inventory: scan local mirror to discover member-related page patterns.

Outputs:
  out/members/inventory.json

This does NOT scrape the live site.
It only reads files under mirror_out/.
Deterministic: same mirror -> same inventory.json.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple


# -------- page classification rules (path-based only) --------

PAGE_RULES: List[Tuple[str, re.Pattern]] = [
    ("member_pages", re.compile(r"(^|/)members(/|$)", re.I)),
    ("event_pages", re.compile(r"(^|/)events(/|$)", re.I)),
    ("club_pages", re.compile(r"(^|/)clubs(/|$)", re.I)),
    ("gallery_pages", re.compile(r"(^|/)gallery(/|$)", re.I)),
    ("news_pages", re.compile(r"(^|/)news(/|$)", re.I)),
    ("faq_pages", re.compile(r"(^|/)faq(/|$)", re.I)),
    ("facts_pages", re.compile(r"(^|/)facts(/|$)", re.I)),
    ("newfaq_pages", re.compile(r"(^|/)newfaq(/|$)", re.I)),
]

SUBTYPE_RULES: List[Tuple[str, re.Pattern]] = [
    ("members_profile", re.compile(r"(^|/)members/(profile|show|view)(/|$)", re.I)),
    ("members_list", re.compile(r"(^|/)members/(list|search)(/|$)", re.I)),
    ("members_home", re.compile(r"(^|/)members/home(/|$)", re.I)),

    ("events_results", re.compile(r"(^|/)events/(results|past)", re.I)),
    ("events_show", re.compile(r"(^|/)events/show(/|$)", re.I)),

    ("clubs_list", re.compile(r"(^|/)clubs/list(/|$)", re.I)),
    ("clubs_showmembers", re.compile(r"(^|/)clubs/(showmembers|members)", re.I)),

    ("gallery_show", re.compile(r"(^|/)gallery/show(/|$)", re.I)),
    ("gallery_list", re.compile(r"(^|/)gallery/(list|index)(/|$)", re.I)),

    ("news_list", re.compile(r"(^|/)news/list", re.I)),
    ("faq_list", re.compile(r"(^|/)faq/list", re.I)),
]


def classify_section(rel_path: str) -> str:
    for name, pat in PAGE_RULES:
        if pat.search(rel_path):
            return name
    return "other_pages"


def classify_subtype(rel_path: str) -> str:
    for name, pat in SUBTYPE_RULES:
        if pat.search(rel_path):
            return name
    return "other"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--mirror-root",
        default="mirror_out/www.footbag.org",
        help="Root directory containing mirrored www.footbag.org files",
    )
    ap.add_argument(
        "--out",
        default="out/members/inventory.json",
        help="Output inventory JSON path",
    )
    ap.add_argument(
        "--max-examples",
        type=int,
        default=20,
        help="Max example paths per bucket",
    )
    args = ap.parse_args()

    mirror_root = Path(args.mirror_root)
    if not mirror_root.exists():
        raise SystemExit(f"Mirror root not found: {mirror_root}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    html_files = sorted(p for p in mirror_root.rglob("*.html") if p.is_file())

    section_counts: Dict[str, int] = {}
    subtype_counts: Dict[str, int] = {}
    examples: Dict[str, List[str]] = {}

    total_bytes = 0

    for p in html_files:
        rel = str(p.relative_to(mirror_root)).replace("\\", "/")
        size = p.stat().st_size
        total_bytes += size

        section = classify_section(rel)
        subtype = classify_subtype(rel)

        section_counts[section] = section_counts.get(section, 0) + 1
        subtype_counts[subtype] = subtype_counts.get(subtype, 0) + 1

        key = f"{section}::{subtype}"
        if key not in examples:
            examples[key] = []
        if len(examples[key]) < args.max_examples:
            examples[key].append(rel)

    inventory = {
        "mirror_root": str(mirror_root),
        "html_file_count": len(html_files),
        "html_total_bytes": total_bytes,
        "section_counts": dict(
            sorted(section_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
        "subtype_counts": dict(
            sorted(subtype_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
        "examples_by_bucket": examples,
        "notes": [
            "Inventory is path-based only; HTML content is not parsed yet.",
            "Next step: inspect member_pages and evidence-bearing pages (events, clubs, gallery, news).",
        ],
    }

    out_path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
