#!/usr/bin/env python3
"""
Stage 2: Canonicalize member records into a new-model-shaped dataset (migration candidates),
join activity evidence, and compute ACTIVE status + confidence.

Inputs:
  out/members/stage1_members_raw.csv
  out/members/stage1_member_activity_events.csv
  (optional) out/members/stage1_member_activity_raw.csv  # gallery low-confidence text evidence

Outputs (under out/members/):
  stage2_members_canonical.csv
  stage2_member_activity.csv
  stage2_members_active.csv
  dedup_report.csv
  field_coverage_report.md
  open_questions.md

Determinism:
  - Stable member_id derived from legacy_member_id
  - Stable evidence_id already created upstream
  - Deterministic sorting on outputs
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple


def stable_member_id(legacy_member_id: str) -> str:
    # Deterministic and stable across runs for same legacy ids
    h = hashlib.sha1(f"legacy_member_id:{legacy_member_id}".encode("utf-8")).hexdigest()
    return "m_" + h[:12]


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: List[Dict[str, str]], cols: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def norm_name_key(name: str) -> str:
    # Conservative: lower + collapse spaces
    return " ".join((name or "").lower().split())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--members-raw", default="out/members/stage1_members_raw.csv")
    ap.add_argument("--events-evidence", default="out/members/stage1_member_activity_events.csv")
    ap.add_argument("--gallery-evidence", default="out/members/stage1_member_activity_raw.csv")
    ap.add_argument("--out-dir", default="out/members")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    members_raw_path = Path(args.members_raw)
    events_ev_path = Path(args.events_evidence)
    gallery_ev_path = Path(args.gallery_evidence)

    if not members_raw_path.exists():
        raise SystemExit(f"Missing: {members_raw_path}")
    if not events_ev_path.exists():
        raise SystemExit(f"Missing: {events_ev_path}")

    members_raw = read_csv(members_raw_path)
    events_ev = read_csv(events_ev_path)
    gallery_ev = read_csv(gallery_ev_path) if gallery_ev_path.exists() else []

    # Index members by legacy_member_id
    members_by_legacy: Dict[str, Dict[str, str]] = {}
    dup_legacy = []
    for m in members_raw:
        lid = m.get("legacy_member_id", "").strip()
        if not lid:
            continue
        if lid in members_by_legacy:
            dup_legacy.append(lid)
        members_by_legacy[lid] = m

    # Build canonical members
    canonical_members: List[Dict[str, str]] = []
    for lid, m in sorted(members_by_legacy.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else kv[0]):
        member_id = stable_member_id(lid)

        # New-model-shaped minimal canonical fields (expand later when modernization docs are found)
        row = {
            "member_id": member_id,
            "legacy_member_id": lid,
            "legacy_username": m.get("legacy_username", ""),
            "name_display": m.get("name_display", ""),
            "joined_raw": m.get("joined_raw", ""),
            "club_ids": m.get("club_ids", ""),
            "club_names": m.get("club_names", ""),
            "club_last_validated_raw": m.get("club_last_validated_raw", ""),
            "has_photo": m.get("has_photo", ""),
            # privacy-aware: keep last_login in restricted column
            "restricted_last_login_raw": m.get("last_login_raw", ""),
            # PII restricted (should usually be blank)
            "restricted_pii_email_raw": m.get("pii_email_raw", ""),
            "restricted_pii_phone_raw": m.get("pii_phone_raw", ""),
            "restricted_pii_address_raw": m.get("pii_address_raw", ""),
            "profile_url": m.get("profile_url", ""),
            "source_path": m.get("source_path", ""),
            "parse_confidence": m.get("parse_confidence", ""),
        }
        canonical_members.append(row)

    # Build activity evidence table (Stage2)
    # Join events evidence by legacy_member_id -> member_id
    stage2_evidence: List[Dict[str, str]] = []

    def add_ev(ev: Dict[str, str], source_system: str):
        lid = (ev.get("legacy_member_id") or "").strip()
        member_id = stable_member_id(lid) if lid else ""
        stage2_evidence.append({
            "evidence_id": ev.get("evidence_id", ""),
            "member_id": member_id,
            "legacy_member_id": lid,
            "evidence_type": ev.get("evidence_type", ""),
            "confidence": ev.get("confidence", ""),
            "privacy_flag": ev.get("privacy_flag", "public"),
            "event_id": ev.get("event_id", ""),
            "event_title": ev.get("event_title", ""),
            "event_date_raw": ev.get("event_date_raw", ""),
            "source_system": source_system,
            "source_path": ev.get("source_path", ""),
            "source_url": ev.get("source_url", ""),
            "link_target": ev.get("link_target", ""),
            "context_text": ev.get("context_text", ""),
        })

    for ev in events_ev:
        add_ev(ev, "events_show")

    # Optional gallery evidence: keep, but do NOT attach to member_id unless legacy_member_id present
    for ev in gallery_ev:
        add_ev(ev, "gallery_show")

    # Deterministic evidence sort
    stage2_evidence.sort(key=lambda r: (r["member_id"], r["evidence_type"], r["event_id"], r["source_path"], r["evidence_id"]))

    # Compute active + confidence
    ev_by_member: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for ev in stage2_evidence:
        if ev["member_id"]:
            ev_by_member[ev["member_id"]].append(ev)

    # Evidence strength map (tunable)
    STRONG_TYPES = {
        "event_role_contact_link",
        "event_role_link",
        "event_participant_link",
        "event_member_link",
    }
    WEAK_TYPES = {
        "gallery_credit_text",
        "gallery_uploader_text",
        "gallery_author_text",
    }

    canonical_members_out: List[Dict[str, str]] = []
    for m in canonical_members:
        mid = m["member_id"]
        evs = ev_by_member.get(mid, [])

        strong = [e for e in evs if e["evidence_type"] in STRONG_TYPES and e["confidence"] == "high"]
        weak = [e for e in evs if e["evidence_type"] in WEAK_TYPES]

        has_login = bool(m.get("restricted_last_login_raw"))

        active = "1" if (len(strong) > 0 or has_login) else "0"

        if len(strong) > 0:
            active_conf = "high"
        elif has_login and len(weak) > 0:
            active_conf = "medium"
        elif has_login:
            active_conf = "medium"
        elif len(weak) >= 2:
            active_conf = "low"
        elif len(weak) == 1:
            active_conf = "low"
        else:
            active_conf = "low"

        # Evidence summary (small, human-friendly; full evidence is in Activity table)
        types = Counter([e["evidence_type"] for e in evs])
        summary = ";".join([f"{k}:{v}" for k, v in sorted(types.items())])

        m2 = dict(m)
        m2.update({
            "active": active,
            "active_confidence": active_conf,
            "evidence_count": str(len(evs)),
            "evidence_summary": summary,
        })
        canonical_members_out.append(m2)

    canonical_members_out.sort(key=lambda r: r["legacy_member_id"])

    # ActiveMembers view
    active_rows = [r for r in canonical_members_out if r["active"] == "1"]

    # Dedup report (conservative)
    # Flag potential duplicates by normalized display name collisions (do NOT merge)
    name_map: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for r in canonical_members_out:
        k = norm_name_key(r.get("name_display", ""))
        if k:
            name_map[k].append(r)

    dedup_rows: List[Dict[str, str]] = []
    for k, group in sorted(name_map.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(group) <= 1:
            continue
        # multiple members share same display name
        ids = ",".join([g["member_id"] for g in group])
        legacy_ids = ",".join([g["legacy_member_id"] for g in group])
        usernames = ",".join([g.get("legacy_username", "") for g in group if g.get("legacy_username")])
        dedup_rows.append({
            "duplicate_key": k,
            "member_ids": ids,
            "legacy_member_ids": legacy_ids,
            "legacy_usernames": usernames,
            "reason": "same_normalized_name_display",
            "recommended_action": "review_manually_do_not_merge_by_default",
        })

    # Field coverage report
    fields = [
        "legacy_username",
        "name_display",
        "joined_raw",
        "club_ids",
        "club_names",
        "club_last_validated_raw",
        "restricted_last_login_raw",
    ]
    total = len(canonical_members_out)
    cov_lines = []
    cov_lines.append(f"# Field coverage report\n")
    cov_lines.append(f"- total_members: {total}\n")
    cov_lines.append("\n## Coverage\n")
    for f in fields:
        filled = sum(1 for r in canonical_members_out if (r.get(f) or "").strip())
        cov_lines.append(f"- {f}: {filled}/{total} ({(filled/total*100.0 if total else 0):.1f}%)\n")

    # Open questions (only blockers)
    oq_lines = []
    oq_lines.append("# Open questions (blockers only)\n")
    oq_lines.append("\n## New model fields not derivable from mirror alone\n")
    oq_lines.append("- Authentication identifiers / emails: mirrored pages may include emails, but we are not outputting them by default.\n")
    oq_lines.append("- Privacy levels / field visibility rules: need modernization docs.\n")
    oq_lines.append("- Roles/permissions model: we infer activity roles (Contact) but cannot map to final role enums without docs.\n")

    # Write outputs
    write_csv(out_dir / "stage2_member_activity.csv", stage2_evidence, cols=[
        "evidence_id","member_id","legacy_member_id","evidence_type","confidence","privacy_flag",
        "event_id","event_title","event_date_raw",
        "source_system","source_path","source_url","link_target","context_text"
    ])

    write_csv(out_dir / "stage2_members_canonical.csv", canonical_members_out, cols=[
        "member_id","legacy_member_id","legacy_username","name_display","joined_raw",
        "club_ids","club_names","club_last_validated_raw","has_photo",
        "active","active_confidence","evidence_count","evidence_summary",
        "restricted_last_login_raw","restricted_pii_email_raw","restricted_pii_phone_raw","restricted_pii_address_raw",
        "profile_url","source_path","parse_confidence"
    ])

    write_csv(out_dir / "stage2_members_active.csv", active_rows, cols=[
        "member_id","legacy_member_id","legacy_username","name_display",
        "active","active_confidence","evidence_count","evidence_summary",
        "profile_url"
    ])

    write_csv(out_dir / "dedup_report.csv", dedup_rows, cols=[
        "duplicate_key","member_ids","legacy_member_ids","legacy_usernames","reason","recommended_action"
    ])

    (out_dir / "field_coverage_report.md").write_text("".join(cov_lines), encoding="utf-8")
    (out_dir / "open_questions.md").write_text("".join(oq_lines), encoding="utf-8")

    print(f"Wrote: {out_dir / 'stage2_members_canonical.csv'} ({len(canonical_members_out)} rows)")
    print(f"Wrote: {out_dir / 'stage2_member_activity.csv'} ({len(stage2_evidence)} rows)")
    print(f"Wrote: {out_dir / 'stage2_members_active.csv'} ({len(active_rows)} rows)")
    print(f"Wrote: {out_dir / 'dedup_report.csv'} ({len(dedup_rows)} rows)")
    print(f"Wrote: {out_dir / 'field_coverage_report.md'}")
    print(f"Wrote: {out_dir / 'open_questions.md'}")

    if dup_legacy:
        print("WARNING: duplicate legacy_member_id rows detected in stage1_members_raw:", sorted(set(dup_legacy))[:10])


if __name__ == "__main__":
    main()
