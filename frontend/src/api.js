import axios from 'axios';

const envBase = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '');

function resolveBaseURL() {
  if (typeof window === 'undefined') {
    return envBase && envBase.endsWith('/api') ? envBase : `${envBase || 'http://localhost:8000'}/api`;
  }

  // Vite dev server: route through the Vite proxy (same origin, no CORS).
  if (import.meta.env.DEV) {
    return '/api';
  }

  // FastAPI serves the built SPA on :8000 — keep requests same-origin.
  if (window.location.port === '8000') {
    return '/api';
  }

  // Deployed (e.g. Vercel): use the configured absolute backend URL.
  if (envBase) {
    return envBase.endsWith('/api') ? envBase : `${envBase}/api`;
  }
  return '/api';
}

const api = axios.create({
  baseURL: resolveBaseURL(), // FastAPI backend
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// On an expired/invalid session, clear local credentials and return to login
// instead of surfacing a cryptic 401 error. Step-up endpoints (MFA code,
// password rotation) use 401 for field-level errors — those must NOT wipe
// the session. Rotation/MFA gates (403) route to the security setup screen.
const STEP_UP_URLS = ['/auth/mfa/challenge', '/auth/mfa/verify', '/auth/change-password', '/auth/mfa/disable'];
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