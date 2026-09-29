# Netraksha Frontend — Officer Kiosk (React 19 + Vite 8 + Tailwind 4)

JS/JSX only (no TypeScript, no `tsconfig`). Sync axios request/response (no React Query, no WebSocket). Lint with `oxlint`.

## Scripts (run in `frontend/`)
- `npm install` — install deps
- `npm run dev` — Vite dev server; `/api` proxied to `http://127.0.0.1:8000` (same-origin, no CORS)
- `npm run build` — production build to `dist/` (served by FastAPI SPA fallback; `sourcemap:false`)
- `npm run lint` — `oxlint` (config `.oxlintrc.json`)
- `npm run preview` — preview built bundle

## Stack
- `react`/`react-dom` 19.2.8, `react-router-dom` 7.18.3 (`BrowserRouter`, lazy routes), `axios` 1.20.0 singleton, `lucide-react`, `clsx` + `tailwind-merge`
- Tailwind 4 via `@tailwindcss/postcss` (`src/index.css` `@import "tailwindcss"` + `@theme` tokens)

## Routes (`src/App.jsx`)
| Path | View | Guard |
|---|---|---|
| `/login` | `views/Login.jsx` (password + supervisor TOTP step-up) | public |
| `/change-password` | `views/SecuritySetup.jsx` (rotation + MFA enroll) | authed (`ProtectedRoute`) |
| `/` | `views/Dashboard.jsx` (Case ID/Timestamp/DocType/Verdict/Status; search by id/doctype) | `SecurityGate` + authed |
| `/scan` | `views/Scanner.jsx` (webcam doc + 14-frame face burst; UUID `Idempotency-Key` header + form fallback) | `SecurityGate` + authed |
| `/case/:id` | `views/CaseReport.jsx` (`GET /cases/:id` + `/provenance`; signed evidence URLs; RBAC override with `version`/`If-Match`, reason ≥3) | `SecurityGate` + authed |
| `/audit` | `views/AuditTrail.jsx` (auditor-only list + chain verify) | `SecurityGate` + authed |
| `*` | `views/NotFound.jsx` | public |

Nav (`components/Sidebar.jsx`): Cases/Scanner/Audit; officer+supervisor see Scanner, supervisor+auditor see Audit. `SecurityGate` forces `/change-password` on `must_change_password`/`mfa_setup_required`. 401 (non-step-up) wipes `localStorage` → `/login`; 403 rotation/MFA gates → `/change-password`.

## Env
- `VITE_API_BASE_URL=http://localhost:8000/api` — must end with `/api`. Ignored in `DEV` and when served from `:8000` (both use same-origin `/api`).
- `VITE_SITE_URL=https://<domain>` — drives `vite.config.js` `seoFiles()` (`%SITE_URL%` in `index.html` + emitted `robots.txt/sitemap.xml/llms.txt`). Known bugs: defaults disagree across `vite.config.js` / `src/config/site.js` / `.env.example`; `OG_IMAGE` ext mismatch (`.jpeg` vs real `.png`); `public/robots.txt|sitemap.xml|llms.txt` ship literal `%SITE_URL%` (only `index.html` is rewritten).
- Backend serves `dist/`; Vercel rewrites `/(.*)→/index.html` (`vercel.json`).

## Known gaps (don't claim done)
- No violet `MOCKED DATA` badge (amber DEMO box / slate notice + chips only); no Aadhaar `XXXX-XXXX-1234` masking (raw values render).
- `EvidenceImage` hardcodes `/api/evidence/view?token=` — use `api.defaults.baseURL` for absolute backends.
- Duplicated `handleVerify` in `AuditTrail.jsx` (second shadows first).
