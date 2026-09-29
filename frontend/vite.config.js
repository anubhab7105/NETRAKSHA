import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'


 
 
 
 const SITE_URL = (process.env.VITE_SITE_URL || 'https://netraksha.xyz').replace(/\/+$/, '')

const BUILD_DATE = new Date().toISOString().slice(0, 10)

const robotsTxt = () => `# Netraksha — See. Verify. Secure.
# Public crawl policy. All application data sits behind officer authentication.

User-agent: *
Allow: /

# Disallow private/authenticated routes
Disallow: /scan
Disallow: /case/
Disallow: /audit
Disallow: /login

# Sitemap
Sitemap: ${SITE_URL}/sitemap.xml

# Host
Host: ${SITE_URL.replace('https://', '')}
`

const sitemapXml = () => `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">
  <url>
    <loc>${SITE_URL}/</loc>
    <lastmod>${BUILD_DATE}</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
    <xhtml:link rel="alternate" hreflang="en-IN" href="${SITE_URL}/" />
    <xhtml:link rel="alternate" hreflang="x-default" href="${SITE_URL}/" />
  </url>
  <url>
    <loc>${SITE_URL}/scan</loc>
    <lastmod>${BUILD_DATE}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
    <xhtml:link rel="alternate" hreflang="en-IN" href="${SITE_URL}/scan" />
    <xhtml:link rel="alternate" hreflang="x-default" href="${SITE_URL}/scan" />
  </url>
  <url>
    <loc>${SITE_URL}/audit</loc>
    <lastmod>${BUILD_DATE}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.6</priority>
    <xhtml:link rel="alternate" hreflang="en-IN" href="${SITE_URL}/audit" />
    <xhtml:link rel="alternate" hreflang="x-default" href="${SITE_URL}/audit" />
  </url>
  <url>
    <loc>${SITE_URL}/login</loc>
    <lastmod>${BUILD_DATE}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.5</priority>
    <xhtml:link rel="alternate" hreflang="en-IN" href="${SITE_URL}/login" />
    <xhtml:link rel="alternate" hreflang="x-default" href="${SITE_URL}/login" />
  </url>
</urlset>
`

const llmsTxt = () => `# Netraksha — See. Verify. Secure.
# Sashastra Seema Bal, Ministry of Home Affairs (Government of India)

## Overview
Netraksha is an AI-assisted forensic screening system for border checkpoints. It provides six-layer document forensics, 3-way biometric face matching, and liveness detection with an explainable Green/Yellow/Red risk verdict for authorized officers.

## Key Pages
- Home / Case Dashboard: ${SITE_URL}/ — Monitor and adjudicate identity screening cases
- Kiosk Scanner: ${SITE_URL}/scan — Capture identity document and traveler's live face for screening
- Audit Trail: ${SITE_URL}/audit — Immutable event ledger of every automated check and officer decision
- Login: ${SITE_URL}/login — Officer authentication portal

## API Endpoints (Backend)
Base URL: ${SITE_URL.replace('netraksha.xyz', 'api.netraksha.xyz')}/
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




function seoFiles() {
  return {
    name: 'ssb-seo-files',
    transformIndexHtml(html) {
      return html.replaceAll('%SITE_URL%', SITE_URL)
    },
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: 'robots.txt', source: robotsTxt() })
      this.emitFile({ type: 'asset', fileName: 'sitemap.xml', source: sitemapXml() })
      this.emitFile({ type: 'asset', fileName: 'llms.txt', source: llmsTxt() })
    },
  }
}


export default defineConfig({
  plugins: [react(), seoFiles()],
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
})
