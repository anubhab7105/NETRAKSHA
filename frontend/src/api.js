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
// instead of surfacing a cryptic 401 error.
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response && err.response.status === 401) {
      localStorage.removeItem('token');
      localStorage.removeItem('role');
      localStorage.removeItem('username');
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    return Promise.reject(err);
  }
);

export default api;