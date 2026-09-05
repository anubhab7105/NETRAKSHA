import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Proxy API calls to the FastAPI backend during local development so the
    // browser talks same-origin (avoids CORS and localhost IPv4/IPv6 mixups).
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/evidence': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})