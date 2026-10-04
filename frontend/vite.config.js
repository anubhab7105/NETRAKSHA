import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'



// Single default for SITE_URL — src/config/site.js mirrors this fallback.
// %SITE_URL% replacement intentionally applies to index.html only (Vite
// transformIndexHtml); robots/sitemap/llms are generated from this value.
const SITE_URL_FALLBACK = 'https://netraksha.xyz'

const BUILD_DATE = new Date().toISOString().slice(0, 10)

const robotsTxt = (siteUrl) => `# Netraksha — See. Verify. Secure.
# Public crawl policy. All application data sits behind officer authentication.

User-agent: *
Allow: /

# Disallow private/authenticated routes
Disallow: /scan
Disallow: /case/
Disallow: /audit
Disallow: /login

# Sitemap
Sitemap: ${siteUrl}/sitemap.xml
`

const sitemapXml = (siteUrl) => `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">
  <url>
    <loc>${siteUrl}/</loc>
    <lastmod>${BUILD_DATE}</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
    <xhtml:link rel="alternate" hreflang="en-IN" href="${siteUrl}/" />
    <xhtml:link rel="alternate" hreflang="x-default" href="${siteUrl}/" />
  </url>
</urlset>
`

const llmsTxt = (siteUrl, apiBase) => `# Netraksha — See. Verify. Secure.
# Sashastra Seema Bal, Ministry of Home Affairs (Government of India)

## Overview
Netraksha is an AI-assisted forensic screening system for border checkpoints. It provides six-layer document forensics, 3-way biometric face matching, and liveness detection with an explainable Green/Yellow/Red risk verdict for authorized officers.

## Key Pages
- Home / Case Dashboard: ${siteUrl}/ — Monitor and adjudicate identity screening cases (authenticated)

## API Endpoints (Backend)
Base URL: ${apiBase} (same-origin /api when the SPA is served by the backend; VITE_API_BASE_URL otherwise)
- POST /screen — Submit document and face images for screening
- GET /cases — List recent screening cases
- GET /cases/:id — Get detailed forensic report for a case
- POST /cases/:id/override — Officer adjudication (clear/deny/escalate)
- GET /audit — Retrieve audit logs with filters

## Data Schema
### Case Object
- id: integer
- timestamp: ISO8601 datetime
- document_type: string (PASSPORT, AADHAAR, etc.)
- verdict: "Green" | "Yellow" | "Red"
- status: "pending_review" | "cleared" | "denied" | "escalated"
- extracted_fields: array of {field_name, extracted_value, database_value, match_status}
- module_results: array of {module_name, status, score, raw_output, evidence_uri}

### Module Types
- gemini_ai: 3-way face match (live vs doc, doc vs db, live vs db) + similarity score
- tamper: Error Level Analysis (ELA) tamper detection
- deepfake: FFT-based deepfake detection metrics
- liveness: Blink-based liveness detection (EAR swing, blink count)
- checksum: MRZ/document checksum validation
- watchlist: Watchlist registry lookup

## Security & Compliance
- All endpoints require Bearer token authentication
- Audit trail is immutable and append-only
- No PII stored in logs beyond case references
- Officer decisions require justification (min 3 characters)
- System verdicts are advisory; officer confirmation required

## Contact
- Organization: Sashastra Seema Bal (SSB)
- Parent: Ministry of Home Affairs, Government of India
- Website: https://ssb.gov.in/
`




function seoFiles(siteUrl, apiBase) {
  return {
    name: 'ssb-seo-files',
    transformIndexHtml(html) {
      return html.replaceAll('%SITE_URL%', siteUrl)
    },
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: 'robots.txt', source: robotsTxt(siteUrl) })
      this.emitFile({ type: 'asset', fileName: 'sitemap.xml', source: sitemapXml(siteUrl) })
      this.emitFile({ type: 'asset', fileName: 'llms.txt', source: llmsTxt(siteUrl, apiBase) })
    },
  }
}


export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const SITE_URL = (env.VITE_SITE_URL || process.env.VITE_SITE_URL || SITE_URL_FALLBACK).replace(/\/+$/, '')
  const API_BASE = (env.VITE_API_BASE_URL || process.env.VITE_API_BASE_URL || `${SITE_URL}/api`).replace(/\/+$/, '')

  return {
  plugins: [react(), seoFiles(SITE_URL, API_BASE)],
  build: {
    sourcemap: false,
    cssCodeSplit: true,
    minify: true,
    chunkSizeWarningLimit: 500,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/react/') || id.includes('node_modules/react-dom/') || id.includes('node_modules/scheduler/')) {
            return 'react-vendor';
          }
          if (id.includes('node_modules/react-router/') || id.includes('node_modules/react-router-dom/')) {
            return 'router';
          }
          if (id.includes('node_modules/lucide-react/')) {
            return 'lucide-icons';
          }
          if (id.includes('node_modules/axios/')) {
            return 'http-client';
          }
        },
        chunkFileNames: 'assets/js/[name]-[hash].js',
        entryFileNames: 'assets/js/[name]-[hash].js',
        assetFileNames: (assetInfo) => {
          const info = assetInfo.name.split('.');
          const ext = info[info.length - 1];
          if (/\.(png|jpe?g|gif|svg|webp|avif|ico)$/.test(assetInfo.name)) {
            return `assets/img/[name]-[hash].${ext}`;
          }
          if (/\.(woff2?|ttf|eot)$/.test(assetInfo.name)) {
            return `assets/fonts/[name]-[hash].${ext}`;
          }
          if (/\.css$/.test(assetInfo.name)) {
            return `assets/css/[name]-[hash].${ext}`;
          }
          return `assets/[name]-[hash].${ext}`;
        },
      },
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  }
})
