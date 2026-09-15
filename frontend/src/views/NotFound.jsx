import React from 'react';
import { Link } from 'react-router-dom';
import { ShieldCheck, ArrowLeft, LogIn } from 'lucide-react';
import SEO from '../components/SEO';

export default function NotFound() {
  const isAuthenticated = Boolean(localStorage.getItem('token'));

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#F7F8FA] px-4 py-10">
      <SEO
        title="Page Not Found"
        description="The requested page does not exist on Netraksha."
        path={window.location.pathname}
        noindex
      />
      <div className="gov-card-padded w-full max-w-[440px] text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl bg-[#123B66] text-white">
          <ShieldCheck size={28} aria-hidden="true" />
        </div>
        <p className="text-xs font-bold uppercase tracking-[0.1em] text-[#1769AA]">Error 404</p>
        <h1 className="mt-1 text-2xl font-bold text-[#172033]">Page not found</h1>
        <p className="mt-2 text-sm text-[#667085]">
          The page you requested does not exist or may have been moved. Use the links below to get back on track.
        </p>
        <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-center">
          {isAuthenticated ? (
            <Link to="/" className="gov-btn gov-btn-primary">
              <ArrowLeft size={16} aria-hidden="true" />
              Back to Case Dashboard
            </Link>
          ) : (
            <Link to="/login" className="gov-btn gov-btn-primary">
              <LogIn size={16} aria-hidden="true" />
              Go to Sign In
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
