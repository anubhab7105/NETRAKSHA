// Central site identity + origin. The origin is overridable at build/deploy
// time via VITE_SITE_URL (see vite.config.js, which uses the same value for
// sitemap.xml / robots.txt / llms.txt and the static canonical tags).
export const SITE_URL = (import.meta.env.VITE_SITE_URL || 'https://www.netraksha.xyz').replace(/\/+$/, '');

export const SITE_NAME = 'Netraksha';
export const SITE_TAGLINE = 'See. Verify. Secure.';
export const DEFAULT_DESCRIPTION =
  'AI-assisted forensic screening of travel credentials: document classification, OCR/MRZ checksums, tamper and deepfake detection, 3-way biometric face matching and liveness checks — with explainable risk verdicts for authorized officers.';
export const OG_IMAGE = `${SITE_URL}/og-image.jpeg`;
