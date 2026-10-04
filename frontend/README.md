# Netraksha Frontend — Officer Kiosk (React 19 + Vite 8 + Tailwind 4)

JS/JSX only (no TypeScript, no `tsconfig`). Sync axios request/response (no React Query, no WebSocket). Lint with `oxlint`.

## Scripts (run in `frontend/`)
- `npm install` — install deps
- `npm run dev` — Vite dev server; `/api` proxied to `http://127.0.0.1:8000` (same-origin, no CORS)
- `npm run build` — production build to `dist/` (served by FastAPI SPA fallback; `sourcemap:false`)
- `npm run lint` — `oxlint` (config `.oxlintrc.json`)
- `npm run preview` — preview built bundle

## Stack
- `react`/`react-dom` 19.2.8, `react-router-dom` 7.18.3 (`BrowserRouter`, lazy routes), `axios` 1.20.0 singleton, `lucide-react` (no `clsx`/`tailwind-merge` — removed, unused)
- Tailwind 4 via `@tailwindcss/postcss` (`src/index.css` `@import "tailwindcss"` + `@theme` tokens)

## Routes (`src/App.jsx`)
| Path | View | Guard |
|---|---|---|
| `/login` | `views/Login.jsx` (password + supervisor TOTP step-up) | public |
| `/change-password` | `views/SecuritySetup.jsx` (rotation + MFA enroll) | authed (`ProtectedRoute`) |
| `/` | `views/Dashboard.jsx` (Case ID/Timestamp/DocType/Verdict/Status; search by id/doctype) | `SecurityGate` + authed |
| `/scan` | `views/Scanner.jsx` (webcam doc + 5-frame lite person burst via `PersonBiometricCapture`; per-intent UUID `Idempotency-Key` in `sessionStorage`, header + form fallback; sequential `toBlob` — no canvas race) | `SecurityGate` + `officer,supervisor` |
| `/case/:id` | `views/CaseReport.jsx` (`GET /cases/:id` + `/provenance` + `/thresholds`; signed evidence URLs; RBAC override with `version`/`If-Match`, reason ≥3) | `SecurityGate` + `officer,supervisor,auditor` |
| `/audit` | `views/AuditTrail.jsx` (auditor-only list + chain verify w/ `verifying` state; `offset+1` clamped to `count`) | `SecurityGate` + `auditor` |
| `*` | `views/NotFound.jsx` | public |

Nav (`components/Sidebar.jsx`): `RoleGate` hides links cosmetically (server still enforces); officer+supervisor see Scanner, auditor-only sees Audit. `SecurityGate` forces `/change-password` on `must_change_password` (all roles) / `mfa_setup_required` (supervisors only). 401 (non-step-up) wipes `localStorage` → `/login`; 403 rotation/MFA gates → `/change-password`. Logout clears only known session keys. 401 (non-step-up) wipes `localStorage` → `/login`; 403 rotation/MFA gates → `/change-password`.

## Env
- `VITE_API_BASE_URL=http://localhost:8000/api` — must end with `/api`. Wins everywhere when set (including `DEV`); otherwise same-origin `/api` in `DEV`, on `:8000`, on Railway, or on allowlisted hosts (`VITE_API_ALLOWLIST`). Base URL is logged at startup; JWT lives in `localStorage` + HttpOnly `nc_session` cookie fallback; CSP/HSTS enforced server-side (`backend/app.py`) + `vercel.json`.
- `VITE_SITE_URL=https://<domain>` — drives `vite.config.js` `seoFiles()` via `loadEnv` (`%SITE_URL%` in `index.html` only, by design; `robots.txt`/`sitemap.xml`/`llms.txt` are generated). Fallback `https://netraksha.xyz` lives once in `vite.config.js` (`SITE_URL_FALLBACK`, mirrored in `src/config/site.js`). Sitemap lists `/` only (private routes stay `Disallow`ed); `llms.txt` uses the real `VITE_API_BASE_URL` (no invented `api.` subdomain).
- Backend serves `dist/`; Vercel rewrites `/api/*` to the Railway backend and `/(.*)→/index.html` for the SPA (`vercel.json`, which already ships CSP/HSTS). `vercel.json` is static JSON so the Railway destination cannot read env at runtime — update the `/api` destination per environment in the Vercel dashboard (or set `VITE_API_BASE_URL` and redeploy). `public/404.html` is only for non-SPA static hosts (relative URLs, inline styles, no CDN).

## Closed gaps (were open, now DONE — verified)
- Violet `MOCKED DATA` badge: `MockedDataBadge` (`gov-badge-violet`) renders for `is_demo`/`is_mocked` in `CaseReport.jsx`.
- Aadhaar `XXXX-XXXX-1234` masking: `maskAadhaar` (doc/DB fields) + `maskPII` (QR payloads, watchlist IDs) in `CaseReport.jsx`; server-side `mask_document_number()` too.
- `EvidenceImage` uses `api.defaults.baseURL` (works with absolute backends).
- Single `handleVerify` in `AuditTrail.jsx` (with `verifying` state; filter submit no longer double-fetches).
- Tamper/physical bands are single-sourced: `GET /api/thresholds` (`pipeline/thresholds.json`, 0.4/0.7) with UI fallback — no stale 0.25/0.50.
- Tailwind v4 important modifier is trailing (`py-12!`, not `!py-12`); `public/404.html` is relative + inline-styles only (no Tailwind CDN).
