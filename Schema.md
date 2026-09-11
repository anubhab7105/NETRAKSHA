# Schema
## Database Design (MVP — Supabase PostgreSQL & SQLite Dual Engine)

Storage is configured using **Supabase PostgreSQL** (cloud-managed PostgreSQL 15/16) as the primary database (`postgresql+asyncpg://...`, `postgresql://` auto-rewritten) with zero-installation setup on Windows, built-in object storage, and a live app dashboard for evaluators. The system maintains an automatic local **SQLite async fallback** (`sqlite+aiosqlite:///screening.db`) so the application operates seamlessly even in offline or network-throttled border scenarios. Selection is via `DATABASE_URL` (empty = SQLite). No Alembic — `init_db()` runs `create_all` plus idempotent `ensure_model_columns` / `ensure_auth_columns` / `ensure_registry_trust_columns` / `ensure_sequences` (re-anchors Postgres SERIALs past `max(id)`) on every startup.

Real authentication is enforced via the `officers` table with bcrypt-only password hashing (passlib, no SHA fallback) and JWT sessions plus supervisor TOTP and forced rotation. 10 tables total.

---

### 1. Tables

**officers**
| Column | Type | Notes |
|---|---|---|
| id | serial PK | autoincrement |
| username | text, unique | |
| password_hash | text | bcrypt only — never plaintext |
| role | text | `officer` \| `supervisor` \| `auditor` |
| unit | text, default `BORDER_UNIT_1` | least-privilege scoping (`BORDER_UNIT_1/2`, `HQ`) |
| created_at | timestamptz, server_default now() | |
| must_change_password | boolean, default false | 403-gates all endpoints until rotation |
| totp_secret | text, nullable | base32; set at MFA enrollment |
| totp_enabled | boolean, default false | supervisors must enroll |
| password_changed_at | timestamptz, nullable | naive UTC (`_utcnow_naive()`) |

**screening_cases**
| Column | Type | Notes |
|---|---|---|
| id | serial PK | |
| officer_id | FK → officers.id | who ran the screening |
| timestamp | timestamptz, server_default now() | |
| document_type | text, nullable | `aadhaar` \| `pan` \| `voter_id` \| `passport` |
| citizen_id | FK → citizens_registry.id, nullable | matched record for demographic + face verification |
| demographic_match | boolean, nullable | |
| risk_score | float, nullable | 0.0–1.0 from Risk Engine |
| verdict | text, nullable | `Green` \| `Yellow` \| `Red` |
| status | text, default `pending_review` | `pending_review` \| `escalated` \| `decided` |
| unit | text, nullable | officer unit snapshot for scoping |
| version | integer, default 0 | optimistic locking (`If-Match` on override) |
| provenance | text, nullable | JSON (code/model/threshold/deps/input hashes) |
| provenance_signature | text, nullable | HMAC-SHA256 with `JWT_SECRET` |
| challenge_type | text, nullable | `blink` \| `head_turn` \| `mouth_open` |

**citizens_registry** *(official reference records; mocked seed data)*
| Column | Type | Notes |
|---|---|---|
| id | serial PK | |
| document_type | text | `aadhaar` \| `pan` \| `voter_id` \| `passport` |
| document_number | text | composite unique `(document_type, document_number)` |
| full_name | text | |
| date_of_birth | text, nullable | YYYY-MM-DD or DD/MM/YYYY |
| gender | text, nullable | `M` \| `F` \| `Other` |
| address | text, nullable | |
| father_or_spouse_name | text, nullable | for PAN / Voter ID |
| photo_uri | text, nullable | registered reference photo for 3-way face |
| source | text, nullable | `authority_import` \| `verified_enrollment` \| `legacy_seed` |
| source_ref | text, nullable | authority batch / enrollment ref |
| verification_method | text, nullable | how the record was verified |
| photo_hash | text, nullable | SHA256 of enrolled photo |
| enrolled_by | text, nullable | requester username |
| approved_by | text, nullable | approver username (four-eyes) |
| last_reconciled_at | timestamptz, nullable | set by reconciliation run |
| reconciliation_status | text, nullable | `ok` / needs-review |

Trust levels derived at screening: `verified` / `legacy` (pre-dual-approval seed, Green possible) / `unverified` (floors verdict at Yellow). Not `is_mocked` — that flag is watchlist/Gemini only.

**registry_enrollments** *(controlled enrollment queue — four-eyes)*
| Column | Type | Notes |
|---|---|---|
| id | serial PK | |
| action | text, default `create` | `create` \| `delete` |
| status | text, default `pending` | `pending` \| `approved` \| `rejected` |
| document_type / document_number / full_name / date_of_birth / gender / address / father_or_spouse_name | various, nullable | staged values |
| photo_uri / photo_hash | text, nullable | staged under `samples/faces/uploads/pending_*` |
| source / source_ref / verification_method | various, nullable | `legacy_seed` rejected as source |
| request_reason / review_note | text, nullable | `request_reason` ≥10 chars, `review_note` ≥3 |
| requested_by_id / requested_by | FK officers.id / text | requester |
| approved_by_id / approved_by | FK officers.id / text, nullable | must differ from requester |
| target_citizen_id | FK citizens_registry.id, nullable | for `delete` |
| resulting_citizen_id | FK citizens_registry.id, nullable | for approved `create` |
| created_at / decided_at | timestamptz | |

**extracted_fields**
| Column | Type | Notes |
|---|---|---|
| id | serial PK | |
| case_id | FK → screening_cases.id | |
| field_name | text | e.g. `document_number`, `full_name`, `date_of_birth`, `address` |
| extracted_value | text, nullable | parsed from document (null if unreadable) |
| database_value | text, nullable | from `citizens_registry` (null when no DB record → `match_status` NULL) |
| match_status | text, default `unverified` | `match` \| `mismatch` \| `unverified` |
| confidence | float, nullable | OCR/parser confidence 0.0–1.0 |

**module_results**
| Column | Type | Notes |
|---|---|---|
| id | serial PK | |
| case_id | FK → screening_cases.id | |
| module_name | text | `tamper` \| `physical_forgery` \| `deepfake` \| `liveness` \| `gemini_ai` \| `watchlist` \| `checksum` |
| score | float, nullable | null + `status='inconclusive'` on failure (Techspec §5) |
| status | text, default `ok` | `ok` \| `inconclusive` |
| raw_output | text (JSON) | full evidence (3-way pairs for `gemini_ai`; local pairs stored alongside; reconciliation table for demographics) |
| evidence_uri | text, nullable | ELA / physical overlay / face side-by-side; null for OCR/deepfake/liveness |
| is_mocked | boolean, default false | true for `watchlist` always and `gemini_ai` when `is_simulated` (drives DEMO notice) |

**officer_actions**
| Column | Type | Notes |
|---|---|---|
| id | serial PK | |
| case_id | FK → screening_cases.id | |
| officer_id | FK → officers.id | |
| action | text | `clear` \| `deny` \| `escalate` (officers cannot `deny`; escalated needs supervisor) |
| reason | text | required, ≥3 chars |
| timestamp | timestamptz, server_default now() | |

**audit_log** *(append-only, hash-chained)*
| Column | Type | Notes |
|---|---|---|
| id | serial PK | |
| actor | text | officer username or `system` |
| action | text | e.g. `screening_completed`, `officer_override:deny`, `login`, `enrollment_approved:create` |
| entity | text, nullable | e.g. `case:{id}` |
| timestamp | timestamptz, server_default now() | |
| immutable | boolean, default true | no UPDATE/DELETE path at app layer (hard DB write-once is production scope) |
| officer_id | integer, nullable | |
| session_id | text, nullable | JWT `jti` |
| request_id | text, nullable | `X-Request-ID` or generated hex |
| device_info | text, nullable | `UA|IP|XFF|XRealIP|unit` |
| file_hashes | text, nullable | JSON SHA256s (truncated in some actions) |
| prev_hash / entry_hash | text, nullable | `HMAC(JWT_SECRET, prev+actor+action+entity)`; verified by `GET /api/audit/verify` |

**screening_idempotency**
| Column | Type | Notes |
|---|---|---|
| id | serial PK | |
| idempotency_key | text (128) | client UUID v4; unique per `(officer_id, idempotency_key)` |
| officer_id | FK → officers.id | |
| session_id | text, default `""` | JWT `jti` |
| input_hash | text (64) | SHA256 over sorted file hashes |
| case_id | FK → screening_cases.id, nullable | null = in-progress claim |
| response_snapshot | text, nullable | JSON replay body |
| created_at | timestamptz | hash-window dedup is 10 min |

**watchlist_entries** *(mocked)*
| Column | Type | Notes |
|---|---|---|
| id | serial PK | |
| name | text | |
| id_number | text, nullable | |
| flag_reason | text, nullable | e.g. Lookout Circular, Interpol notices |

Backed by a `WatchlistProvider` interface at the app layer (Techspec §3), so this table can be swapped for a real registry client later without touching the Risk Engine.

---

### 2. Relationships
```
officers 1───* screening_cases
officers 1───* officer_actions
officers 1───* registry_enrollments (requested_by / approved_by)
citizens_registry 1───* screening_cases (citizen_id, nullable)
screening_cases 1───* extracted_fields
screening_cases 1───* module_results
screening_cases 1───* officer_actions
screening_cases 1───* screening_idempotency (case_id, nullable until complete)
citizens_registry 1───* registry_enrollments (target/resulting)
(watchlist_entries is looked up, not FK'd — matched by name/ID string per Techspec §3)
```

### 3. Retention / lifecycle (in scope, contrary to early drafts)
- Staged enrollment photos live under `samples/faces/uploads/pending_*` until approve/reject (secure-deleted otherwise).
- Orphan biometric scan (`GET /api/citizens/orphans`) + supervisor cleanup (`POST /api/citizens/orphans/cleanup`) zero-overwrites unreferenced files; audited as `biometric_retention:deleted|orphan_cleanup`.
- Reconciliation (`POST /api/citizens/reconciliation/run`) stamps `last_reconciled_at/reconciliation_status`.

### 4. Password hashing — resolved
`passlib[bcrypt]` only (`bcrypt==4.0.1` pinned). SHA-256 fallback was removed; unknown-user logins dummy-verify against a fixed bcrypt hash to avoid user enumeration.
