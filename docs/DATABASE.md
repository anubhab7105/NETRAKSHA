# Database Schema

## Database Schema


**11 tables** (`backend/models.py:1`) — Supabase PostgreSQL in production, SQLite (`aiosqlite`) only for isolated `:memory:` fixtures in `tests/test_auth_security.py`.

```
officers  ─┬─< screening_cases ─┬─< extracted_fields
           │                    ├─< module_results
           │                    ├─< officer_actions
           │                    └─< (provenance, version, unit, challenge_type)
           └─< officer_actions
                registry_enrollments (dual-approval queue)
citizens_registry ─┬─< screening_cases
                   └─< iris_templates (encrypted, per-eye)

audit_log (append-only, hash-chained: prev_hash → entry_hash via HMAC-SHA256)
screening_idempotency (uq: officer_id+key, ix: officer+session+input_hash)
watchlist_entries (mocked or real)
```

| Table | Key columns |
|---|---|
| `officers` | `username` (unique), `password_hash` (bcrypt), `role` (`officer`/`supervisor`/`auditor`), `unit` (`BORDER_UNIT_1`/`BORDER_UNIT_2`/`HQ`), `must_change_password`, `totp_secret`/`totp_enabled`, `password_changed_at` |
| `citizens_registry` | `document_type`/`document_number` (unique together), `full_name`, `date_of_birth`, `gender`, `address`, `photo_uri` (local path **or** `http(s)` / Storage path `img/<object>`), trust: `source`/`source_ref`/`verification_method`/`photo_hash`/`enrolled_by`/`approved_by`/`reconciliation_status` |
| `registry_enrollments` | `action` (`create`/`delete`), `status` (`pending`/`approved`/`rejected`), staged payload + `requested_by`/`approved_by`, `target_citizen_id`/`resulting_citizen_id` |
| `screening_cases` | `officer_id`, `citizen_id`, `document_type`, `verdict` (`Green`/`Yellow`/`Red`), `status` (`pending_review`/`escalated`/`decided`), `risk_score`, `unit`, `version` (optimistic locking), `provenance` (JSON) + `provenance_signature` (HMAC), `challenge_type` |
| `extracted_fields` | `case_id`, `field_name`, `extracted_value`/`database_value`, `match_status` (`match`/`mismatch`/`unverified`), `confidence` |
| `iris_templates` | `citizen_id`, `template` (base64 encrypted), `mask`, `quality`, `eye` (`left`/`right`), `enrolled_by` |
| `module_results` | `case_id`, `module_name`, `score`, `status` (`ok`/`inconclusive`), `raw_output` (JSON), `evidence_uri`, `is_mocked` |
| `officer_actions` | `case_id`, `officer_id`, `action` (`clear`/`deny`/`escalate`), `reason` (≥ 3 chars) |
| `audit_log` | `actor`, `action`, `entity`, `immutable`, `officer_id`, `session_id` (JWT `jti`), `request_id`, `device_info`, `file_hashes` (JSON), `prev_hash`, `entry_hash` (HMAC chain) |
| `screening_idempotency` | `idempotency_key` (128), `officer_id`, `session_id`, `input_hash` (SHA-256), `case_id`, `response_snapshot` (JSON), `created_at` |
| `watchlist_entries` | `name`, `id_number`, `flag_reason` |

**Startup self-heal** (`backend/database.py:103` — `init_db`):

- `ensure_model_columns()` — adds any ORM-mapped column missing from the live DB (Postgres `information_schema` / SQLite `PRAGMA`).
- `ensure_registry_trust_columns()` / `ensure_auth_columns()` — backfills post-audit columns.
- `ensure_sequences()` — re-anchors `SERIAL` sequences past `max(id)` on Postgres (legacy explicit-ID DBs).
- Backfills `NULL` flags (`must_change_password`, `totp_enabled`, `version`).

Registry photos: `_resolve_db_photo()` downloads `http(s)` or Supabase Storage `img/<object>` refs once into `$TMPDIR/netraksha_registry_photos` (8 s timeout, 5 MB cap, magic-byte check) for both Gemini Image 3 and local 3-way. Failures degrade to `partial` with `db_pairs_unavailable_reason` (`no_registry_photo` | `registry_photo_missing_on_server` | `registry_photo_download_failed`), never halt.

---
