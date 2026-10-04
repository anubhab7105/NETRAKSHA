import axios from 'axios';

// NOTE on auth storage: the session JWT lives in localStorage (`token`) so the
// kiosk survives a reload; every request still sends it as `Authorization:
// Bearer`. XSS would leak it — the backend therefore also sets an HttpOnly
// `nc_session` cookie fallback, and CSP/HSTS headers are enforced server-side
// (see backend/app.py `_security_headers_middleware`) + vercel.json. Never log
// the token; `resolveBaseURL` below only logs the (non-secret) base URL.

const envBase = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '');

// Hosts that are always served same-origin (Vite dev proxy or backend SPA).
// Extend via VITE_API_ALLOWLIST="host1,host2" instead of hardcoding more.
const allowlistExtra = (import.meta.env.VITE_API_ALLOWLIST || '')
  .split(',')
  .map((h) => h.trim().toLowerCase())
  .filter(Boolean);
const SAME_ORIGIN_HOSTS = new Set([
  'netraksha.xyz',
  'www.netraksha.xyz',
  'sih-weld-psi.vercel.app',
  ...allowlistExtra,
]);

function ensureApiSuffix(url) {
  if (!url) return '/api';
  return url.endsWith('/api') ? url : `${url}/api`;
}

function resolveBaseURL() {
  // Same-origin when the page itself is served by the backend (:8000) or the
  // Vite dev server (proxy `/api` -> 127.0.0.1:8000) — unless an explicit
  // VITE_API_BASE_URL is set, which now wins everywhere including DEV.
  if (typeof window !== 'undefined') {
    const port = window.location.port;
    const host = window.location.hostname.toLowerCase();
    const isBackendOrigin = port === '8000' || host.endsWith('.up.railway.app');
    if (!envBase && (import.meta.env.DEV || isBackendOrigin || SAME_ORIGIN_HOSTS.has(host))) {
      return '/api';
    }
  } else if (!envBase) {
    return '/api';
  }

  if (envBase) {
    if (!(envBase.startsWith('http://') || envBase.startsWith('https://'))) {
      console.warn(`[api] VITE_API_BASE_URL ignored (must be absolute http(s)): ${envBase}`);
      return '/api';
    }
    if (!envBase.endsWith('/api')) {
      console.warn(`[api] VITE_API_BASE_URL should end with /api — appending: ${envBase}`);
    }
    return ensureApiSuffix(envBase);
  }
  return '/api';
}

const baseURL = resolveBaseURL();
if (typeof window !== 'undefined') {
  // eslint-disable-next-line no-console
  console.info(`[api] baseURL=${baseURL}`);
}

const api = axios.create({
  baseURL,
  timeout: 90000,
  withCredentials: true,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});



const STEP_UP_URLS = ['/auth/mfa/challenge', '/auth/mfa/verify', '/auth/mfa/setup', '/auth/change-password', '/auth/mfa/disable'];
api.interceptors.response.use(
  (res) => res,
  (err) => {
    const url = err.config?.url || '';
    const isStepUp = STEP_UP_URLS.some((u) => url.includes(u));
    if (err.response && err.response.status === 401 && !isStepUp) {
      localStorage.removeItem('token');
      localStorage.removeItem('role');
      localStorage.removeItem('username');
      localStorage.removeItem('must_change_password');
      localStorage.removeItem('mfa_setup_required');
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    if (err.response && err.response.status === 403) {
      const detail = String(err.response?.data?.detail || '');
      if (/PASSWORD_CHANGE_REQUIRED|MFA_SETUP_REQUIRED/.test(detail)) {
        if (window.location.pathname !== '/change-password') {
          window.location.href = '/change-password';
        }
      }
    }
    return Promise.reject(err);
  }
);

export default api;



export function apiErrorMessage(err, fallback = 'Request failed.') {
  const status = err?.response?.status;
  const data = err?.response?.data;
  let detail = data?.detail;
  if (Array.isArray(detail)) {
    detail = detail
      .map((d) => (typeof d === 'string' ? d : d?.msg || JSON.stringify(d)))
      .join('; ');
  } else if (detail && typeof detail === 'object') {
    try {
      detail = JSON.stringify(detail);
    } catch {
      detail = '';
    }
  }
  if (detail) return status ? `HTTP ${status}: ${detail}` : String(detail);
  if (err?.request && !err?.response) return 'No response from server. Check your connection and retry.';
  return fallback;
}
