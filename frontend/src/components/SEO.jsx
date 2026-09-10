import { useEffect } from 'react';
import { SITE_URL, SITE_NAME, SITE_TAGLINE, DEFAULT_DESCRIPTION, OG_IMAGE } from '../config/site';

// Upserts a <meta> or <link> tag in <head>, keyed by name/property/rel.
function upsert(selector, create) {
  let el = document.head.querySelector(selector);
  if (!el) {
    el = create();
    document.head.appendChild(el);
  }
  return el;
}

function setMeta(attr, key, content) {
  const el = upsert(`meta[${attr}="${key}"]`, () => {
    const m = document.createElement('meta');
    m.setAttribute(attr, key);
    return m;
  });
  el.setAttribute('content', content);
}

function setCanonical(href) {
  const el = upsert('link[rel="canonical"]', () => {
    const l = document.createElement('link');
    l.rel = 'canonical';
    return l;
  });
  el.setAttribute('href', href);
}

/**
 * Per-page document metadata. Keeps every route's <title>, meta description,
 * canonical URL, social tags and crawl directives unique (SPAs otherwise keep
 * the static index.html head for every route).
 *
 * No third-party dependency: imperative DOM updates inside one effect.
 */
export default function SEO({ title, description = DEFAULT_DESCRIPTION, path = '/', noindex = false }) {
  useEffect(() => {
    const fullTitle = title ? `${title} — ${SITE_NAME}` : `${SITE_NAME} — ${SITE_TAGLINE}`;
    const canonical = `${SITE_URL}${path}`;

    document.title = fullTitle;
    setMeta('name', 'description', description);
    setMeta('name', 'robots', noindex ? 'noindex, nofollow' : 'index, follow');
    setCanonical(canonical);

    setMeta('property', 'og:title', fullTitle);
    setMeta('property', 'og:description', description);
    setMeta('property', 'og:url', canonical);
    setMeta('property', 'og:image', OG_IMAGE);

    setMeta('name', 'twitter:title', fullTitle);
    setMeta('name', 'twitter:description', description);
    setMeta('name', 'twitter:image', OG_IMAGE);
  }, [title, description, path, noindex]);

  return null;
}
