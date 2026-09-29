import axios from 'axios';

const envBase = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '');

function resolveBaseURL() {
  // Dev and :8000 always use same-origin /api so VITE_API_BASE_URL cannot misroute local traffic.
  if (typeof window === 'undefined') {
    return envBase && envBase.endsWith('/api') ? envBase : `${envBase || 'http://localhost:8000'}/api`;
  }

  
  if (import.meta.env.DEV) {
    return '/api';
  }

  
  if (window.location.port === '8000') {
    return '/api';
  }

  
  
  
  
  const host = window.location.hostname.toLowerCase();
  if (host === 'netraksha.xyz' || host === 'www.netraksha.xyz' || host === 'sih-weld-psi.vercel.app') {
    return '/api';
  }

  
  
  
  if (envBase && (envBase.startsWith('http://') || envBase.startsWith('https://'))) {
    return envBase.endsWith('/api') ? envBase : `${envBase}/api`;
  }
  
  if (host.endsWith('.up.railway.app')) {
    return '/api';
  }
  return '/api';
}

const api = axios.create({
  baseURL: resolveBaseURL(), 
  timeout: 90000, 
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});





const STEP_UP_URLS = ['/auth/mfa/challenge', '/auth/mfa/verify', '/auth/change-password', '/auth/mfa/disable'];
api.interceptors.response.use(
  (res) => res,
  (err) => {
    const url = err.config?.url || '';
    // Exempt step-up calls from session wipe so MFA enrollment cannot log itself out.
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