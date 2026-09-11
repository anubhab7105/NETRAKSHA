import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import Sidebar from './components/Sidebar';

// Route-level code splitting: each view ships as its own chunk and is only
// fetched when its route is first visited (keeps the login bundle small).
const Login = lazy(() => import('./views/Login'));
const SecuritySetup = lazy(() => import('./views/SecuritySetup'));
const Dashboard = lazy(() => import('./views/Dashboard'));
const Scanner = lazy(() => import('./views/Scanner'));
const CaseReport = lazy(() => import('./views/CaseReport'));
const AuditTrail = lazy(() => import('./views/AuditTrail'));
const NotFound = lazy(() => import('./views/NotFound'));

function RouteLoader() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center text-slate-400" role="status" aria-label="Loading page">
      <Loader2 className="animate-spin" size={28} />
    </div>
  );
}

const ProtectedRoute = ({ children }) => {
  const token = localStorage.getItem('token');
  if (!token) return <Navigate to="/login" replace />;
  return (
    <div className="flex min-h-screen w-full flex-col bg-background md:h-screen md:flex-row md:overflow-hidden">
      <Sidebar />
      <main className="relative flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8 min-w-0">
        {/* Background ambient light effects */}
        <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] rounded-full bg-primary/10 blur-[120px] pointer-events-none"></div>
        <div className="absolute bottom-[-10%] right-[-10%] w-[30%] h-[30%] rounded-full bg-accent/10 blur-[100px] pointer-events-none"></div>

        <div className="relative z-10 max-w-7xl mx-auto">
          {children}
        </div>
      </main>
    </div>
  );
};

// Rotation/MFA gates are enforced server-side too (403); this keeps the
// officer from landing on a dead dashboard before clearing them.
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
