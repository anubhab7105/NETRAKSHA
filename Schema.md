# Schema
## Database Design (MVP — Supabase PostgreSQL & SQLite Dual Engine)

Storage is configured using **Supabase PostgreSQL** (cloud-managed PostgreSQL 15/16) as the primary database, providing standard PostgreSQL connectivity (`postgresql+asyncpg://...`), zero-installation setup on Windows, built-in object storage, and a live app dashboard for evaluators. The system maintains an automatic local **SQLite async fallback** (`sqlite+aiosqlite:///screening.db`) so the application operates seamlessly even in offline or network-throttled border scenarios.

Real authentication is enforced via the `officers` table with bcrypt password hashing and JWT/session tokens. The schema below implements full tracking for multi-document classification (Aadhaar, PAN, Voter ID, Passport), demographic database reconciliation, 3-way face verification, and append-only audit logging.

---

### 1. Tables

**officers** *(new — required because real login was confirmed)*
| Column | Type | Notes |
|---|---|---|
| id | UUID / serial PK | |
| username | text, unique | |
| password_hash | text | never store plaintext — see Rules.md |
| role | text | `officer` \| `supervisor` \| `auditor` (Design.md §3 role gating) |
| created_at | timestamptz | |

**screening_cases**
| Column | Type | Notes |
|---|---|---|
| id | UUID / serial PK | |
| officer_id | FK → officers.id | who ran/reviewed the screening |
| timestamp | timestamptz | |
| document_type | text | `aadhaar` \| `pan` \| `voter_id` \| `passport` |
| citizen_id | FK → citizens_registry.id, nullable | matched database record for demographic & face verification |
| demographic_match | boolean | true if extracted Name, DOB, Doc No match DB |
| risk_score | numeric | from Risk Engine (0.0 to 1.0) |
| verdict | text | `Green` \| `Yellow` \| `Red` |
| status | text | `pending_review` \| `decided` |

**citizens_registry** *(official reference records for Indian identity documents & passports)*
| Column | Type | Notes |
|---|---|---|
| id | serial PK | |
| document_type | text | `aadhaar` \| `pan` \| `voter_id` \| `passport` |
| document_number | text, unique | e.g. 12-digit Aadhaar, 10-char PAN, EPIC No, Passport No |
| full_name | text | legal registered name |
| date_of_birth | text / date | YYYY-MM-DD or DD/MM/YYYY |
| gender | text | `M` \| `F` \| `Other` |
| address | text | registered residential address |
| father_or_spouse_name | text, nullable | for PAN / Voter ID records |
| photo_uri | text | path/URI to registered reference photograph for 3-way face verification |

**extracted_fields**
| Column | Type | Notes |
|---|---|---|
| id | serial PK | |
| case_id | FK → screening_cases.id | |
| field_name | text | e.g. `document_number`, `full_name`, `date_of_birth`, `address` |
| extracted_value | text | parsed from document (null if unreadable) |
| database_value | text, nullable | corresponding value from `citizens_registry` |
| match_status | text | `match` \| `mismatch` \| `unverified` |
| confidence | numeric | OCR/parser confidence (0.0 to 1.0) |

**module_results**
| Column | Type | Notes |
|---|---|---|
| id | serial PK | |
| case_id | FK → screening_cases.id | |
| module_name | text | `doc_classifier` \| `ocr_demographic` \| `tamper` \| `deepfake` \| `face_verification` \| `liveness` \| `watchlist` |
| score | numeric | nullable — null + `status='inconclusive'` on module failure (Techspec §5) |
| status | text | `ok` \| `inconclusive` |
| raw_output | jsonb | full module evidence (for `face_verification`: 3-way pair verdicts [Live vs Doc, Doc vs DB, Live vs DB], similarity, visual_reasoning, feature_analysis; for `ocr_demographic`: field reconciliation table) |
| evidence_uri | text | e.g. path to ELA overlay image or 3-way composite photo; nullable |
| is_mocked | boolean | true for `watchlist` and `citizens_registry` (drives the "MOCKED DATA" badge) |

**officer_actions**
| Column | Type | Notes |
|---|---|---|
| id | serial PK | |
| case_id | FK → screening_cases.id | |
| officer_id | FK → officers.id | |
| action | text | `clear` \| `deny` \| `escalate` |
| reason | text | free text, required |
| timestamp | timestamptz | |

**audit_log**
| Column | Type | Notes |
|---|---|---|
| id | serial PK | |
| actor | text | officer username or `system` |
| action | text | |
| entity | text | e.g. `case:{id}` |
| timestamp | timestamptz | |
| immutable | boolean | default true — no UPDATE/DELETE path exposed at the app layer (append-only by convention at MVP scale; a hard DB-level write-once constraint is production scope, source PDF §2.5) |

**watchlist_entries** *(mocked)*
| Column | Type | Notes |
|---|---|---|
| id | serial PK | |
| name | text | |
| id_number | text | |
| flag_reason | text | |

Backed by a `WatchlistProvider` interface at the app layer (Techspec §3), so this table can be swapped for a real registry client later without touching the Risk Engine.

---

### 2. Relationships
```
officers 1───* screening_cases
screening_cases 1───* extracted_fields
screening_cases 1───* module_results
screening_cases 1───* officer_actions
officers 1───* officer_actions
(watchlist_entries is looked up, not FK'd — matched by name/ID string per Techspec §3)
```

### 3. Explicitly out of MVP schema scope (per Prd.md §4 non-goals)
- `checkpoints` table / multi-checkpoint support
- Biometric-template-only storage, envelope encryption, retention/lifecycle policies (source PDF §6.2, §7)
- Write-once DB constraint enforcement for `audit_log` (app-level append-only is the MVP substitute)

### 4. Open question
Exact password-hashing library/approach for `officers.password_hash` isn't specified anywhere in the source docs — default assumption is a standard library like `passlib`/`bcrypt`, but flag if you want something specific.