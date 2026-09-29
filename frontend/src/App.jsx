import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Loader2, ShieldCheck } from 'lucide-react';
import Sidebar from './components/Sidebar';



const Login = lazy(() => import('./views/Login'));
const SecuritySetup = lazy(() => import('./views/SecuritySetup'));
const Dashboard = lazy(() => import('./views/Dashboard'));
const Scanner = lazy(() => import('./views/Scanner'));
const CaseReport = lazy(() => import('./views/CaseReport'));
const AuditTrail = lazy(() => import('./views/AuditTrail'));
const NotFound = lazy(() => import('./views/NotFound'));

function RouteLoader() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center text-[#667085]" role="status" aria-label="Loading page">
      <Loader2 className="animate-spin" size={28} />
    </div>
  );
}

function GovTopBar() {
  const role = localStorage.getItem('role') || 'officer';
  const username = localStorage.getItem('username') || 'Officer';
  return (
    <header className="sticky top-0 z-30 border-b border-[#D9DEE7] bg-white/95 backdrop-blur">
      {}
      <div className="flex h-1" aria-hidden="true">
        <div className="flex-1 bg-[#F59E0B]" />
        <div className="flex-1 bg-[#E8EDF3]" />
        <div className="flex-1 bg-[#16803C]" />
      </div>
      <div className="mx-auto flex h-14 max-w-[1280px] items-center gap-3 px-4 sm:px-6">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#123B66] text-white" aria-hidden="true">
          <ShieldCheck size={20} />
        </div>
        <div className="min-w-0 leading-tight">
          <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[#667085]">
            Government of India · Ministry of Home Affairs
          </p>
          <p className="truncate text-[15px] font-bold text-[#123B66]">
            NETRAKSHA <span className="font-medium text-[#667085]">— AI-Based Identity Verification</span>
          </p>
        </div>
        <div className="ml-auto hidden items-center gap-3 sm:flex">
          <span className="gov-badge gov-badge-blue">{role.toUpperCase()}</span>
          <span className="max-w-[160px] truncate text-sm font-medium text-[#172033]" title={username}>
            {username}
          </span>
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[#123B66] text-xs font-bold text-white" aria-hidden="true">
            {String(username).slice(0, 1).toUpperCase()}
          </span>
        </div>
      </div>
    </header>
  );
}

const ProtectedRoute = ({ children }) => {
  const token = localStorage.getItem('token');
  if (!token) return <Navigate to="/login" replace />;
  return (
    <div className="flex min-h-screen w-full flex-col bg-[#F7F8FA] md:h-screen md:flex-row md:overflow-hidden">
      <div className="flex min-w-0 flex-1 flex-col md:overflow-hidden">
        <GovTopBar />
        <div className="flex min-h-0 flex-1 flex-col md:flex-row md:overflow-hidden">
          <Sidebar />
          <main className="min-w-0 flex-1 overflow-x-hidden overflow-y-auto p-4 sm:p-6 lg:p-8">
            <div className="mx-auto max-w-[1280px]">
              {children}
            </div>
            <footer className="mx-auto mt-8 max-w-[1280px] border-t border-[#D9DEE7] pt-4 pb-2">
              <p className="text-xs text-[#98A2B3]">
                NETRAKSHA · Sashastra Seema Bal verification workstation · Official use only — all actions are logged to the immutable audit trail.
              </p>
            </footer>
          </main>
        </div>
      </div>
    </div>
  );
};



const SecurityGate = ({ children }) => {
  const token = localStorage.getItem('token');
  if (!token) return <Navigate to="/login" replace />;
  if (localStorage.getItem('must_change_password') === '1' ||
      localStorage.getItem('mfa_setup_required') === '1') {
    return <Navigate to="/change-password" replace />;
  }
  return children;
};

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<RouteLoader />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/change-password" element={<ProtectedRoute><SecuritySetup /></ProtectedRoute>} />
          <Route path="/" element={<SecurityGate><ProtectedRoute><Dashboard /></ProtectedRoute></SecurityGate>} />
          <Route path="/scan" element={<SecurityGate><ProtectedRoute><Scanner /></ProtectedRoute></SecurityGate>} />
          <Route path="/case/:id" element={<SecurityGate><ProtectedRoute><CaseReport /></ProtectedRoute></SecurityGate>} />
          <Route path="/audit" element={<SecurityGate><ProtectedRoute><AuditTrail /></ProtectedRoute></SecurityGate>} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
