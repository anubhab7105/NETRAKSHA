import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Single source of truth for the production origin. Custom domain switch:
// set VITE_SITE_URL (e.g. https://sentinel.example.in) in the environment /
// Vercel project settings and everything below follows automatically —
// canonical tags, sitemap.xml, robots.txt, llms.txt and Open Graph URLs.
const SITE_URL = (process.env.VITE_SITE_URL || 'https://sih-weld-psi.vercel.app').replace(/\/+$/, '')

const BUILD_DATE = new Date().toISOString().slice(0, 10)

const robotsTxt = () => `# SSB Sentinel — Identity Screening Portal
# Public crawl policy. All application data sits behind officer authentication.

User-agent: *
Allow: /
Disallow: /api/
Disallow: /evidence/

Sitemap: ${SITE_URL}/sitemap.xml
`

const sitemapXml = () => `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>${SITE_URL}/</loc>
    <lastmod>${BUILD_DATE}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>${SITE_URL}/login</loc>
    <lastmod>${BUILD_DATE}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>
</urlset>
`

const llmsTxt = () => `# SSB Sentinel — AI Identity Document Screening

> SSB Sentinel is an AI-assisted forensic identity-screening system used by
> officers of the Sashastra Seema Bal (Ministry of Home Affairs, Government of
> India) at border checkpoints. It evaluates travel credentials across six
> forensic layers — document classification, OCR/MRZ checksums, database
> cross-verification, tamper (ELA) analysis, deepfake (FFT) detection, 3-way
> biometric face matching and liveness detection — and returns an explainable
> Green / Yellow / Red risk verdict with a human-in-the-loop decision step.
> Human officers always make the final adjudication.

The web application is officer-facing and requires authentication. Public
metadata lives at the URLs below.

## Pages

- [Officer Login](${SITE_URL}/login): Secure sign-in for authorized officers.
- [Case Dashboard](${SITE_URL}/): Authenticated overview of screening cases.

## Resources

- [Sitemap](${SITE_URL}/sitemap.xml): Index of public routes.
- [Source code](https://github.com/soumyajit-cys/Python%20Rule-Based-Fake-Identity-Document-Screening-System): Repository (Smart India Hackathon, Problem Statement 26188).
`

// Emits robots.txt / sitemap.xml / llms.txt at build time and resolves the
// %SITE_URL% token inside index.html, so the deployment origin lives in one
// place (VITE_SITE_URL) instead of being hardcoded in a dozen spots.
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

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), seoFiles()],
  build: {
    // Never ship source maps to production (prevents source reconstruction
    // from the published bundle).
    sourcemap: false,
    cssCodeSplit: true,
    minify: 'esbuild',
    chunkSizeWarningLimit: 500,
    rollupOptions: {
      output: {
        // Split heavy vendors out of the app chunk for parallel download
        // and long-term caching.
        manualChunks: {
          'react-vendor': ['react', 'react-dom', 'scheduler'],
          'router': ['react-router', 'react-router-dom'],
          'icons': ['lucide-react'],
          'http-client': ['axios'],
        },
        // Optimize chunk naming for caching
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
