# MAPPING_OLD_TO_NEW (Mirror → Canonical Member Model v0.1)

**Status:** *PROVISIONAL* — mapping is derived from **public mirror evidence only**.  
Modernization user stories / design decisions were **not located in-repo** at time of writing, so this mapping targets the **mirror-derived canonical model** defined in `SCHEMA_NEW_MEMBER_MODEL.md` (v0.1).

**Principles**
- No live scraping; mirror only.
- No guessing; unknown stays blank.
- Provenance preserved: each extracted value links to `source_path` and/or `source_url`.
- Privacy-aware: PII and last-login fields remain in `restricted_*` columns and are hidden by default.

---

## 1) Source systems in the mirror

### A) Member profile pages
- Pattern: `/members/profile/<legacy_member_id>/`
- Local: `mirror_out/www.footbag.org/members/profile/<legacy_member_id>/index.html`
- Primary join key: `legacy_member_id`

### B) Event pages (activity evidence)
- Pattern: `/events/show/<event_id>/`
- Local: `mirror_out/www.footbag.org/events/show/<event_id>/index.html`
- Activity evidence: role links to `/members/profile/<legacy_member_id>`

### C) Gallery pages (optional evidence)
- Pattern: `/gallery/show/<gallery_id>/`
- Local: `mirror_out/www.footbag.org/gallery/show/<gallery_id>/index.html`
- Usually name-only credit text; rarely linked to member profile IDs.

---

## 2) Field mapping: Mirror → Canonical Member (v0.1)

Canonical schema sections:
- Member.identity
- Member.profile
- Member.status
- Member.provenance
- Member.restricted (PII)

### A) Identity

| Mirror observation | Source location | Canonical field | Transform / rule | Notes |
|---|---|---|---|---|
| `<legacy_member_id>` from URL path | `/members/profile/<id>/` | `legacy_member_id` | parse digits from path | **required** |
| derived canonical ID | derived | `member_id` | `m_` + sha1("legacy_member_id:<id>")[:12] | deterministic |
| “Member Profile for <username>” in HTML title/h1 | profile page | `legacy_username` | parse username token | optional; may be blank |
| profile canonical URL | derived | `profile_url` | `http://www.footbag.org/members/profile/<id>` | deterministic |

### B) Public profile fields

| Mirror observation | Example | Canonical field | Transform / rule | Notes |
|---|---|---|---|---|
| displayed real name block | `Josh Penney` | `name_display` | collapse whitespace; preserve diacritics | do not split first/last without spec |
| Joined date | `Joined: 04/13/02` | `joined_raw` | store raw string | do not normalize to ISO yet |
| Club membership link(s) | `/clubs/show/<club_id>` | `club_ids` | join multiple with `,` | keep deterministic ordering |
| Club display name(s) | `New York Footbag Association` | `club_names` | join multiple with `,` | aligned to club_ids if possible |
| Club last validated | `last validated: 09/11/13` | `club_last_validated_raw` | store raw string | may exist even when other profile fields absent |
| presence of profile photo indicator | `has_photo` | `has_photo` | "1" if detected, else "0" | extraction heuristic; mirror-derived |

### C) Status fields (derived)

| Input signals | Canonical field | Rule | Notes |
|---|---|---|---|
| event-linked evidence exists | `active` | `"1"` if any high-confidence event evidence | strong signal |
| last-login present | `active` | `"1"` if no event evidence but last-login present | weaker presence signal |
| neither signal | `active` | `"0"` | reserved for broader mirrors |
| evidence mix | `active_confidence` | `high` if event evidence; `medium` if login-only; `low` reserved | current implementation yields only high/medium |
| linked evidence count | `evidence_count` | count evidence rows with member_id | from `stage2_member_activity.csv` |
| evidence type summary | `evidence_summary` | `type:count;type:count` | stable sorted by type |

### D) Provenance & parse quality

| Mirror observation | Canonical field | Rule |
|---|---|---|
| local HTML path | `source_path` | relative path under mirror root |
| parser confidence flag | `parse_confidence` | `high|medium|low` from extractor |

---

## 3) Restricted / sensitive field handling

We explicitly store potential sensitive fields in restricted columns.

| Mirror observation | Canonical field | Handling rule | Output policy |
|---|---|---|---|
| Last login timestamp | `restricted_last_login_raw` | store raw string | **hidden in xlsx**; exclude from default exports |
| Email | `restricted_pii_email_raw` | store raw if ever found | do not expose by default |
| Phone | `restricted_pii_phone_raw` | store raw if ever found | do not expose by default |
| Address | `restricted_pii_address_raw` | store raw if ever found | do not expose by default |

**Important:** restricted fields should never be used for identity merges or other irreversible logic in v0.1.

---

## 4) Field mapping: Mirror → ActivityEvidence

ActivityEvidence is populated from mirror event pages (high confidence) and optionally gallery pages (low confidence).

### A) Events → ActivityEvidence (high confidence)

| Mirror observation | Canonical evidence_type | Confidence | Linkage rule |
|---|---|---:|---|
| Event “Contact:” section linking to `/members/profile/<id>` | `event_role_contact_link` | high | `legacy_member_id` extracted from href; join to member_id deterministically |

Mapped fields:

| Extracted from event page | ActivityEvidence field | Notes |
|---|---|---|
| deterministic evidence hash (from page + link + type) | `evidence_id` | should be stable across runs |
| linked member profile id | `legacy_member_id` | join key |
| canonical member id | `member_id` | derived from legacy_member_id |
| event id from URL | `event_id` | `/events/show/<event_id>` |
| event title text | `event_title` | raw |
| event date tokens (if present) | `event_date_raw` | raw |
| local event html path | `source_path` | provenance |
| canonical URL | `source_url` | provenance |
| linked profile href | `link_target` | e.g. `/members/profile/12028` |
| surrounding snippet | `context_text` | audit trail |
| `source_system` | `events_show` | fixed |

### B) Gallery → ActivityEvidence (low confidence; optional)

Most gallery pages provide credit/uploader text but **do not provide stable member IDs**.

| Mirror observation | Canonical evidence_type | Confidence | Linkage rule |
|---|---|---:|---|
| credit text without member link | `gallery_credit_text` | low | **no automatic member_id join** (leave member_id blank) |
| uploader name text | `gallery_uploader_text` | low | same |
| direct member link present (rare) | `gallery_member_link` | high/medium | join via legacy_member_id in link |

**v0.1 policy:** gallery evidence is stored for audit/review but **does not flip ACTIVE** unless it includes a stable member profile link.

---

## 5) Discard / ignore list (v0.1)

We intentionally discard or defer fields when they are:
- not present in the public mirror
- not reliably parseable
- likely sensitive
- not spec-defined

| Candidate field | Decision | Why |
|---|---|---|
| normalized joined date (ISO) | defer | requires spec for date interpretation + locale |
| first_name / last_name split | defer | non-deterministic for multi-part names |
| location fields (city/state/country) | defer | not consistently present in observed profiles; needs extraction validation |
| email/phone/address export | restricted only | privacy |
| role assignment on Member entity | defer | modernization RBAC not defined; keep as evidence rows |
| aggressive dedup/merge | defer | high risk; review-only via `dedup_report.csv` |

---

## 6) Future: when we get a full DB dump

When a full member database export becomes available, we will:

### A) Replace / enrich identity fields
- authoritative email/username identifiers
- account status (verified, banned, deactivated)
- canonical profile fields (country, city, etc.)

### B) Add modern auth fields (spec-driven)
- login identifier type (email/username)
- password reset tokens (not migrated)
- OAuth provider mappings (if used)

### C) Improve active/inactive classification
- membership renewal/payment status (if exists)
- recent activity timestamps (authoritative)
- imported activity history beyond what mirror contains

### D) Resolve duplicates with stronger signals
- email match
- internal user IDs
- confirmed aliases

**Important:** the mirror-derived canonical `member_id` should remain stable for test data, but production migration will likely use a different canonical ID strategy based on the modern DB.

---

## 7) Mapping completeness checklist (v0.1)

This mapping is considered complete for v0.1 if:

- Every column in `stage1_members_raw.csv` maps to:
  - a canonical Member field, OR
  - a restricted field, OR
  - an explicit discard/defer note here
- Every evidence row in `stage1_member_activity_events.csv` maps to ActivityEvidence
- Outputs:
  - `stage2_members_canonical.csv`
  - `stage2_member_activity.csv`
  - `dedup_report.csv`
  - `members_canonical.xlsx`
  are reproducible and deterministic from the same mirror inputs

---

## 8) Open questions (true blockers for spec-derived mapping)

These questions require modernization docs (user stories + design decisions):

1) What is the modern system’s **primary login identifier** (email vs username vs OAuth)?
2) What are the **privacy visibility levels** for member fields (public/private/friends/admin)?
3) Do “members” map to **accounts** 1:1, or do we support profiles without accounts?
4) What is the canonical list of **roles/permissions** and how should legacy “Contact” map?
5) What does “member since” mean in the new system (join date vs paid membership start)?

Until answered, this mapping remains mirror-derived and provisional.

---