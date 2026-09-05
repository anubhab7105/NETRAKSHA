import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import Login from './views/Login';
import Dashboard from './views/Dashboard';
import Scanner from './views/Scanner';
import CaseReport from './views/CaseReport';
import AuditTrail from './views/AuditTrail';

const ProtectedRoute = ({ children }) => {
  const token = localStorage.getItem('token');
  if (!token) return <Navigate to="/login" replace />;
  return (
    <div className="flex h-screen w-full bg-background overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-8 relative">
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

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
        <Route path="/scan" element={<ProtectedRoute><Scanner /></ProtectedRoute>} />
        <Route path="/case/:id" element={<ProtectedRoute><CaseReport /></ProtectedRoute>} />
        <Route path="/audit" element={<ProtectedRoute><AuditTrail /></ProtectedRoute>} />
      </Routes>
    </BrowserRouter>
  );
}
