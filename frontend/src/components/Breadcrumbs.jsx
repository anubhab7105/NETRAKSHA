import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight, Home } from 'lucide-react';
import { SITE_URL } from '../config/site';

/**
 * Breadcrumb trail for the authenticated layout. Renders accessible markup
 * (aria-label + ol) and injects a matching BreadcrumbList JSON-LD block so
 * crawlers see the same hierarchy users do.
 *
 * items: [{ label, to }] — the last item is the current page (no link).
 */
export default function Breadcrumbs({ items }) {
  useEffect(() => {
    const id = 'breadcrumb-jsonld';
    const existing = document.getElementById(id);
    if (existing) existing.remove();

    const script = document.createElement('script');
    script.type = 'application/ld+json';
    script.id = id;
    script.textContent = JSON.stringify({
      '@context': 'https://schema.org',
      '@type': 'BreadcrumbList',
      itemListElement: items.map((item, i) => ({
        '@type': 'ListItem',
        position: i + 1,
        name: item.label,
        ...(item.to ? { item: `${SITE_URL}${item.to}` } : {}),
      })),
    });
    document.head.appendChild(script);
    return () => script.remove();
  }, [items]);

  return (
    <nav aria-label="Breadcrumb" className="mb-4">
      <ol className="flex flex-wrap items-center gap-1.5 text-sm text-slate-400">
        {items.map((item, i) => {
          const isLast = i === items.length - 1;
          return (
            <li key={`${item.label}-${i}`} className="flex items-center gap-1.5">
              {i > 0 && <ChevronRight size={14} className="text-slate-600" aria-hidden="true" />}
              {isLast || !item.to ? (
                <span aria-current={isLast ? 'page' : undefined} className={isLast ? 'font-medium text-slate-200' : undefined}>
                  {i === 0 && <Home size={14} className="mr-1 inline-block -translate-y-px" aria-hidden="true" />}
                  {item.label}
                </span>
              ) : (
                <Link to={item.to} className="rounded hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-primary transition-colors">
                  {i === 0 && <Home size={14} className="mr-1 inline-block -translate-y-px" aria-hidden="true" />}
                  {item.label}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
