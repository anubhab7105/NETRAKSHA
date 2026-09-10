// Central site identity + origin. The origin is overridable at build/deploy
// time via VITE_SITE_URL (see vite.config.js, which uses the same value for
// sitemap.xml / robots.txt / llms.txt and the static canonical tags).
export const SITE_URL = (import.meta.env.VITE_SITE_URL || 'https://sih-weld-psi.vercel.app').replace(/\/+$/, '');

export const SITE_NAME = 'SSB Sentinel';
export const SITE_TAGLINE = 'Identity Screening Portal';
export const DEFAULT_DESCRIPTION =
  'AI-assisted forensic screening of travel credentials: document classification, OCR/MRZ checksums, tamper and deepfake detection, 3-way biometric face matching and liveness checks — with explainable risk verdicts for authorized officers.';
export const OG_IMAGE = `${SITE_URL}/og-image.png`;
