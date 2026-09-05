import axios from 'axios';

const rawBaseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';
const trimmedBaseURL = rawBaseURL.replace(/\/+$/, '');
const baseURL = trimmedBaseURL.endsWith('/api') ? trimmedBaseURL : `${trimmedBaseURL}/api`;

const api = axios.create({
  baseURL, // FastAPI backend
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default api;
