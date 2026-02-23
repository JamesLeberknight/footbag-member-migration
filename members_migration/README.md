# Member migration (mirror-derived) pipeline (v0)

This pipeline builds a **deterministic, provenance-preserving member dataset**
from a **local public mirror** of Footbag.org.

This dataset is intended for:
- modernization schema validation
- import/load testing
- stakeholder review

It is **not** a full production migration (no private DB dump).

---

## Scope & guarantees

- **Source**: public HTML pages from a local mirror only
- **No live scraping**
- **No guessing**: unknown fields remain blank
- **Deterministic**: same mirror → same outputs
- **Provenance preserved**: every extracted value traces back to a source path / URL
- **Privacy-aware**: potentially sensitive fields are restricted by default

---

## Inputs

- Local mirror root: `mirror_out/www.footbag.org`
- Member profile pages: `/members/profile/<legacy_member_id>/`
- Event pages: `/events/show/<event_id>/`

---

## Outputs (under `out/members/`)

- `stage1_members_raw.csv`  
- `stage1_member_activity_events.csv`  
- `stage2_member_activity.csv`  
- `stage2_members_canonical.csv`  
- `stage2_members_active.csv`  
- `dedup_report.csv`  
- `field_coverage_report.md`  
- `open_questions.md`  
- `members_canonical.xlsx`  

---

## Privacy policy

- Only **publicly visible mirrored fields** are extracted.
- Potential PII fields (email, phone, address, last login) are written only to:
  - `restricted_*` columns
- Restricted columns are **hidden by default** in the spreadsheet.
- No restricted fields are used to derive ACTIVE status except last-login presence.

---

## How to run (end-to-end)

From repo root:

```bash
# 1) Inventory (optional but recommended)
python scripts/00_inventory_members.py \
  --mirror-root mirror_out/www.footbag.org \
  --out out/members/inventory.json

# 2) Extract member profiles (Stage 1A)
python members_migration/04_members_extract_mirror.py \
  --mirror-root mirror_out/www.footbag.org \
  --out out/members/stage1_members_raw.csv

# 3) Extract event activity evidence (Stage 1C)
python members_migration/04_member_activity_extract_events.py \
  --mirror-root mirror_out/www.footbag.org \
  --out out/members/stage1_member_activity_events.csv

# 4) Canonicalize members + compute ACTIVE (Stage 2)
python members_migration/05_members_canonicalize.py \
  --members-raw out/members/stage1_members_raw.csv \
  --events-evidence out/members/stage1_member_activity_events.csv \
  --out-dir out/members

# 5) Build spreadsheet
python members_migration/06_members_build_spreadsheet.py \
  --out-dir out/members \
  --out-xlsx out/members/members_canonical.xlsx
