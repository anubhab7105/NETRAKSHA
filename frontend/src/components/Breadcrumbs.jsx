import React, { useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight, House } from 'lucide-react';
import { SITE_URL } from '../config/site';








export default function Breadcrumbs({ items = [] }) {
  const safeItems = useMemo(() => (Array.isArray(items) ? items : []), [items]);
  const jsonLd = useMemo(
    () =>
      JSON.stringify({
        '@context': 'https://schema.org',
        '@type': 'BreadcrumbList',
        itemListElement: safeItems.map((item, i) => ({
          '@type': 'ListItem',
          position: i + 1,
          name: item.label,
          ...(item.to ? { item: `${SITE_URL}${item.to}` } : {}),
        })),
      }),
    [safeItems],
  );
  useEffect(() => {
    const id = 'breadcrumb-jsonld';
    const existing = document.getElementById(id);
    if (existing) existing.remove();

    const script = document.createElement('script');
    script.type = 'application/ld+json';
    script.id = id;
    script.textContent = jsonLd;
    document.head.appendChild(script);
    return () => script.remove();
  }, [jsonLd]);

  return (
    <nav aria-label="Breadcrumb">
      <ol className="flex flex-wrap items-center gap-1.5 text-[13px] text-[#667085]">
        {safeItems.map((item, i) => {
          const isLast = i === safeItems.length - 1;
          return (
            <li key={`${item.label}-${i}`} className="flex items-center gap-1.5">
              {i > 0 && <ChevronRight size={14} className="text-[#98A2B3]" aria-hidden="true" />}
              {isLast || !item.to ? (
                <span aria-current={isLast ? 'page' : undefined} className={isLast ? 'font-semibold text-[#123B66]' : undefined}>
                  {i === 0 && <House size={14} className="mr-1 inline-block -translate-y-px" aria-hidden="true" />}
                  {item.label}
                </span>
              ) : (
                <Link to={item.to} className="rounded hover:text-[#123B66] hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1769AA]">
                  {i === 0 && <House size={14} className="mr-1 inline-block -translate-y-px" aria-hidden="true" />}
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
