# SCHEMA_NEW_MEMBER_MODEL (Mirror-derived v0.1)

**Status:** *PROVISIONAL* — derived from **public mirror evidence only**.  
**Not yet derived from modernization user stories / design decisions** (docs not located in-repo at time of writing).  
This schema is intentionally conservative: it defines only what we can support deterministically today, and it cleanly marks unknowns.

---

## Goals

This canonical model is designed to:

- support **deterministic migration test data** into the modernized site
- preserve **provenance** (every extracted value traceable to a source path/URL)
- be **privacy-aware** (PII fields exist only as restricted columns; not exported by default)
- support **identity stability** across repeated runs on the same mirror

---

## Non-goals (v0.1)

- Final auth/account schema (blocked pending modernization docs)
- Full RBAC / permissions model (blocked pending modernization docs)
- Aggressive dedup/merge of identities (review-only; no silent merges)
- Inferring missing data (no guessing)

---

## Definitions

### Canonical IDs
- **member_id**: deterministic canonical ID generated from legacy_member_id  
  - current implementation: `member_id = "m_" + sha1("legacy_member_id:<id>")[:12]`
  - **stable** across runs given identical inputs
- **legacy_member_id**: numeric ID from mirror URLs: `/members/profile/<legacy_member_id>/`  
  - treated as the **primary join key** where available

### Provenance
Every non-trivial extracted value should be traceable to:
- `source_path` (relative path within mirror root)
- `profile_url` or `source_url` (where applicable)

### Privacy
Fields that could be sensitive (email/phone/address/last-login) are stored only in:
- `restricted_*` columns  
and **must be hidden by default** in spreadsheets and excluded from default exports unless explicitly needed.

---

## Entity overview

This model uses four core entities:

1) **Member** — canonical identity & basic public profile  
2) **MemberActivityEvidence** — “active” signals and audit trail  
3) **MemberDuplicateCandidate** — non-destructive dedup review table  
4) **FieldCoverageReport** — completeness stats for reviewers

This aligns with your current workbook tabs:
- Members
- ActivityEvidence
- DuplicatesReview
- FieldCoverage

---

## Entity: Member

### Purpose
Represents one canonical member identity record used for migration/import testing.

### Uniqueness rules
- `member_id` is unique (canonical)
- `legacy_member_id` is unique **within a given mirror dataset**
- `legacy_username` is **not guaranteed** unique (may be blank or reused historically)

### Fields

| Field | Type | Required | Source | Notes |
|---|---|---:|---|---|
| member_id | string | ✅ | derived | deterministic stable ID |
| legacy_member_id | string | ✅ | mirror URL | `/members/profile/<id>` |
| legacy_username | string | ❌ | profile page | extracted from title/header where possible |
| name_display | string | ❌ | profile page | public display name; may be blank |
| joined_raw | string | ❌ | profile page | raw join date string (do not normalize without spec) |
| club_ids | string | ❌ | profile page | pipe/comma-delimited if multiple; mirror-derived |
| club_names | string | ❌ | profile page | display names aligned to club_ids when possible |
| club_last_validated_raw | string | ❌ | profile page | raw “last validated” string |
| has_photo | string ("1"/"0") | ❌ | profile page | boolean-ish; mirror-derived |
| active | string ("1"/"0") | ✅ | derived | computed from evidence rules |
| active_confidence | enum | ✅ | derived | `high|medium|low` |
| evidence_count | integer-as-string | ✅ | derived | number of evidence rows linked to member |
| evidence_summary | string | ✅ | derived | summary counts by evidence_type |
| profile_url | string | ✅ | derived | canonical URL on old site |
| source_path | string | ✅ | mirror | provenance to the profile HTML |
| parse_confidence | enum | ✅ | derived | `high|medium|low` from extractor |

#### Restricted fields (privacy-aware)
These exist but should be hidden by default and excluded from default exports.

| Field | Type | Required | Notes |
|---|---|---:|---|
| restricted_last_login_raw | string | ❌ | presence signal; treat as restricted |
| restricted_pii_email_raw | string | ❌ | do not expose by default |
| restricted_pii_phone_raw | string | ❌ | do not expose by default |
| restricted_pii_address_raw | string | ❌ | do not expose by default |

---

## Entity: MemberActivityEvidence

### Purpose
Stores one row per activity signal with provenance. This is the **audit trail** behind `active` classification.

### Uniqueness rules
- `evidence_id` is unique (deterministic upstream; should be stable if input pages unchanged)

### Fields

| Field | Type | Required | Notes |
|---|---|---:|---|
| evidence_id | string | ✅ | stable id from extractor |
| member_id | string | ✅ | canonical link (may be blank for name-only evidence) |
| legacy_member_id | string | ❌ | join key; may be blank in name-only cases |
| evidence_type | string | ✅ | see evidence types below |
| confidence | enum | ✅ | `high|medium|low` (currently high for event links) |
| privacy_flag | enum | ✅ | `public` (only public sources in mirror) |
| event_id | string | ❌ | for event-derived evidence |
| event_title | string | ❌ | raw title from event page |
| event_date_raw | string | ❌ | raw date-like token if present |
| source_system | string | ✅ | e.g. `events_show`, `gallery_show` |
| source_path | string | ✅ | provenance |
| source_url | string | ✅ | old-site URL |
| link_target | string | ❌ | e.g. `/members/profile/<id>` |
| context_text | string | ❌ | local context window around evidence |

### Evidence types (current observed)
These are **observed from mirror**, not spec-driven.

- `event_role_contact_link` (high-confidence linked role)
- `event_role_link` (reserved; future)
- `event_member_link` (reserved; future participant links if present)
- `gallery_credit_text` (name-only; low-confidence; not used to flip active in v0)

> Note: In v0.1 ACTIVE is computed from **event-linked evidence** or **last-login presence**, not from name-only evidence.

---

## Entity: MemberDuplicateCandidate

### Purpose
Non-destructive review table for possible duplicate identities. No merges are applied automatically.

### Fields

| Field | Type | Required | Notes |
|---|---|---:|---|
| duplicate_key | string | ✅ | normalized name key (conservative) |
| member_ids | string | ✅ | comma-separated |
| legacy_member_ids | string | ✅ | comma-separated |
| legacy_usernames | string | ❌ | comma-separated |
| reason | string | ✅ | e.g. `same_normalized_name_display` |
| recommended_action | string | ✅ | always review; do not merge by default |

---

## Entity: FieldCoverageReport

### Purpose
Reviewer-facing completeness metrics.

### Fields
Produced as markdown and/or tabular sheet:

- total_members
- per-field filled_count
- per-field filled_pct

No strict schema required beyond repeatability.

---

## ACTIVE classification (v0.1 semantics)

A member is **ACTIVE** if at least one of:

1) Has ≥1 **high-confidence linked evidence** from event pages (e.g. `event_role_contact_link`), OR  
2) Has `restricted_last_login_raw` present on the profile page (presence signal)

`active_confidence`:
- **high**: any event-linked evidence exists
- **medium**: login-only presence (no event evidence)
- **low**: reserved for weaker signals (not used to flip active in v0.1)

---

## Authentication, roles, privacy levels (BLOCKED)

Modernization docs are required to finalize:

### Authentication identifiers
Likely candidates (DO NOT ASSUME):
- email as login?
- username?
- external auth provider?

**Current mirror-derived model provides:**
- `legacy_member_id`
- `legacy_username` (sometimes)
- restricted email (if ever present)

### Roles / permissions
Mirror evidence can indicate *legacy roles* (e.g., event contact), but we cannot map those to modern RBAC enums without design decisions.

**For now:**
- store role-like signals only as **activity evidence**
- do not assign durable roles on the Member entity

### Privacy levels / profile visibility
We cannot interpret intended visibility rules from mirror alone.

**For now:**
- treat PII and last-login as restricted
- treat name_display as public
- treat club affiliation as public (as shown on mirror profile pages)

---

## Required future inputs (to finalize schema)

To upgrade this from *PROVISIONAL* → *SPEC-DERIVED* we need:

1) modernization user stories for:
   - accounts
   - member profile fields
   - privacy controls
   - admin/moderator roles
2) design decisions for:
   - authentication (email vs username vs OAuth)
   - identity uniqueness constraints
   - profile field normalization rules
   - deactivation/deletion semantics

Once available, we will:
- promote/rename fields to match modern spec
- add true required/optional rules
- add normalized types (dates, enums)
- define role mappings explicitly

---

## Suggested canonical JSON shape (for future import testing)

This is a **shape example** (not normative beyond fields defined above):

```json
{
  "member_id": "m_0123abcd4567",
  "legacy": {
    "legacy_member_id": "12007",
    "legacy_username": "jpenney",
    "profile_url": "http://www.footbag.org/members/profile/12007"
  },
  "profile": {
    "name_display": "Josh Penney",
    "joined_raw": "04/13/02",
    "clubs": [
      {
        "club_id": "nyfa",
        "club_name": "New York Footbag Association",
        "last_validated_raw": "09/11/13"
      }
    ],
    "has_photo": true
  },
  "status": {
    "active": true,
    "active_confidence": "high",
    "evidence_count": 3,
    "evidence_summary": "event_role_contact_link:3"
  },
  "provenance": {
    "source_path": "members/profile/12007/index.html",
    "parse_confidence": "high"
  },
  "restricted": {
    "last_login_raw": "Sun Oct 30 08:52:07 2011",
    "pii_email_raw": "",
    "pii_phone_raw": "",
    "pii_address_raw": ""
  }
}