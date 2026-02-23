
#!/usr/bin/env python3
"""
Phase 0C: Scan mirrored HTML for member-id/link patterns and evidence signals.

Outputs:
  out/members/inventory_evidence.json

Deterministic: same mirror -> same output.
No live scraping.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

# --- patterns we care about ---
RE_MEMBER_PROFILE_PATH = re.compile(r"/members/profile/(\d+)", re.I)
RE_MEMBER_PROFILE_QS   = re.compile(r"/members/profile\?id=(\d+)", re.I)
RE_POPUPPROFILE        = re.compile(r"popupprofile\(['\"]?(\d+)['\"]?\)", re.I)

RE_CLUBID_QS           = re.compile(r"/clubs/showmembers\?clubid=(\d+)", re.I)
RE_EVENT_SHOW_PATH     = re.compile(r"/events/show/(\d+)", re.I)
RE_GALLERY_SHOW_PATH   = re.compile(r"/gallery/show/(\d+)", re.I)

# evidence-ish text signals (loose, we only count presence here)
EVIDENCE_KEYWORDS = [
    ("gallery_credit_word", re.compile(r"\bcredit\b", re.I)),
    ("gallery_uploader_word", re.compile(r"\bupload", re.I)),
    ("event_results_word", re.compile(r"\bresults\b", re.I)),
    ("club_officer_word", re.compile(r"\bofficer\b|\bpresident\b|\bsecretary\b|\btreasurer\b", re.I)),
    ("author_word", re.compile(r"\bauthor\b|\bposted by\b", re.I)),
]

def classify_path(rel: str) -> str:
    rel_low = rel.lower().lstrip("/")

    def has(prefix: str) -> bool:
        prefix = prefix.lower().strip("/")
        return rel_low == prefix or rel_low.startswith(prefix + "/") or ("/" + prefix + "/") in ("/" + rel_low)

    if has("members"):
        return "members"
    if has("events"):
        return "events"
    if has("clubs"):
        return "clubs"
    if has("gallery"):
        return "gallery"
    if has("news"):
        return "news"
    if has("faq") or has("facts") or has("newfaq"):
        return "faq"
    return "other"

def sample_add(samples: Dict[str, List[str]], key: str, value: str, limit: int) -> None:
    if key not in samples:
        samples[key] = []
    if len(samples[key]) < limit and value not in samples[key]:
        samples[key].append(value)

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mirror-root", default="mirror_out/www.footbag.org")
    ap.add_argument("--out", default="out/members/inventory_evidence.json")
    ap.add_argument("--max-files", type=int, default=0, help="0 = all html files")
    ap.add_argument("--max-samples", type=int, default=25)
    args = ap.parse_args()

    root = Path(args.mirror_root)
    if not root.exists():
        raise SystemExit(f"Mirror root not found: {root}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    html_files = sorted(p for p in root.rglob("*.html") if p.is_file())
    if args.max_files and args.max_files > 0:
        html_files = html_files[: args.max_files]

    counts_by_section = Counter()
    member_profile_link_counts = Counter()
    evidence_keyword_counts = Counter()

    # where patterns were seen (for debugging / review)
    examples = {}
    samples = {}

    # aggregated “how many files contain X”
    files_with_member_link = Counter()
    files_with_popup = Counter()

    for p in html_files:
        rel = str(p.relative_to(root)).replace("\\", "/")
        section = classify_path(rel)
        counts_by_section[section] += 1

        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        # member link patterns
        prof_ids = set(RE_MEMBER_PROFILE_PATH.findall(text)) | set(RE_MEMBER_PROFILE_QS.findall(text))
        popup_ids = set(RE_POPUPPROFILE.findall(text))

        if prof_ids:
            files_with_member_link[section] += 1
            member_profile_link_counts[section] += len(prof_ids)
            sample_add(samples, f"{section}::member_profile_paths", rel, args.max_samples)

        if popup_ids:
            files_with_popup[section] += 1
            sample_add(samples, f"{section}::popupprofile", rel, args.max_samples)

        # evidence keywords
        for k, pat in EVIDENCE_KEYWORDS:
            if pat.search(text):
                evidence_keyword_counts[f"{section}::{k}"] += 1
                sample_add(samples, f"{section}::{k}", rel, args.max_samples)

        # capture examples of exact URL patterns (only a few)
        # (we store patterns, not full content)
        if RE_CLUBID_QS.search(text):
            sample_add(samples, f"{section}::club_showmembers_link_present", rel, args.max_samples)
        if RE_EVENT_SHOW_PATH.search(text):
            sample_add(samples, f"{section}::event_show_link_present", rel, args.max_samples)
        if RE_GALLERY_SHOW_PATH.search(text):
            sample_add(samples, f"{section}::gallery_show_link_present", rel, args.max_samples)

    result = {
        "mirror_root": str(root),
        "html_files_scanned": len(html_files),
        "counts_by_section": dict(counts_by_section),
        "files_with_member_profile_links": dict(files_with_member_link),
        "files_with_popupprofile_js": dict(files_with_popup),
        "member_profile_link_counts_total_ids_seen": dict(member_profile_link_counts),
        "evidence_keyword_file_counts": dict(evidence_keyword_counts),
        "sample_paths": samples,
        "notes": [
            "Counts are based on HTML text scans; this does not extract structured fields yet.",
            "Next step: Stage 1 extraction using the strongest identifier patterns (prefer /members/profile/<id> links).",
        ],
    }

    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote: {out_path}")

if __name__ == "__main__":
    main()
