import React from 'react';
import { Link } from 'react-router-dom';
import { ShieldAlert, ArrowLeft, LogIn } from 'lucide-react';
import SEO from '../components/SEO';

export default function NotFound() {
  const isAuthenticated = Boolean(localStorage.getItem('token'));

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background px-4 py-8">
      <SEO
        title="Page Not Found"
        description="The requested page does not exist on the SSB Sentinel identity screening portal."
        path={window.location.pathname}
        noindex
      />
      {/* Background blobs */}
      <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] rounded-full bg-primary/20 blur-[120px] pointer-events-none"></div>
      <div className="absolute bottom-[-20%] right-[-10%] w-[50%] h-[50%] rounded-full bg-accent/20 blur-[120px] pointer-events-none"></div>

      <div className="glass-panel relative z-10 w-full max-w-md animate-fade-in-up p-8 text-center">
        <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-danger/10 text-danger">
          <ShieldAlert size={32} aria-hidden="true" />
        </div>
        <p className="text-sm font-semibold uppercase tracking-widest text-primary">Error 404</p>
        <h1 className="mt-1 text-2xl font-bold text-white">Page not found</h1>
        <p className="mt-2 text-sm text-slate-400">
          The page you requested does not exist or may have been moved. Use the links below to get back on track.
        </p>
        <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-center">
          {isAuthenticated ? (
            <Link
              to="/"
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-primary to-accent px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
            >
              <ArrowLeft size={16} aria-hidden="true" />
              Back to Case Dashboard
            </Link>
          ) : (
            <Link
              to="/login"
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-primary to-accent px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
            >
              <LogIn size={16} aria-hidden="true" />
              Go to Sign In
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
