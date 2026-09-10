import React from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { Shield, Scan, List, LogOut, User, ScrollText } from 'lucide-react';
import api from '../api';

export default function Sidebar() {
  const navigate = useNavigate();
  const role = localStorage.getItem('role') || 'officer';
  const username = localStorage.getItem('username') || 'Unknown';

  const handleLogout = async () => {
    try {
      await api.post('/auth/logout');
    } catch (e) {
      // ignore
    }
    localStorage.clear();
    navigate('/login');
  };

  // Role-based navigation (audit P2 §4):
  //   officer:    Case Dashboard + Kiosk Scanner
  //   supervisor: Case Dashboard + Kiosk Scanner + Audit Trail
  //   auditor:    Case Dashboard + Audit Trail (no scanner)
  const showScanner = role === 'officer' || role === 'supervisor';
  const showAudit = role === 'supervisor' || role === 'auditor';

  return (
    <aside className="z-20 flex w-full flex-col justify-between border-b border-slate-700/50 bg-surface/80 backdrop-blur-xl md:h-screen md:w-64 md:shrink-0 md:border-b-0 md:border-r md:bg-surface/50">
      <div>
        <Link to="/" className="flex items-center gap-3 border-b border-slate-700/50 p-4 sm:p-5 md:p-6" aria-label="Netraksha — go to Case Dashboard">
          <div className="bg-primary/20 p-2 rounded-lg text-primary">
            <Shield size={24} />
          </div>
          <div>
            {/* Site brand — not a page heading (each view owns its own h1). */}
            <p className="text-lg font-bold bg-clip-text text-transparent bg-gradient-to-r from-primary to-accent">Netraksha</p>
            <p className="text-xs text-slate-400">See. Verify. Secure.</p>
          </div>
        </Link>

        <nav aria-label="Primary navigation" className="flex gap-2 overflow-x-auto p-3 sm:p-4 md:block md:space-y-2 md:overflow-visible">
          <NavLink
            to="/"
            className={({isActive}) => `flex shrink-0 items-center gap-2 px-3 py-2.5 rounded-lg text-sm transition-all md:gap-3 md:px-4 md:py-3 md:text-base ${isActive ? 'bg-primary/10 text-primary font-medium shadow-[inset_0_-2px_0_0_currentColor] md:shadow-[inset_2px_0_0_0_currentColor]' : 'text-slate-300 hover:bg-white/5 hover:text-white'}`}
          >
            <List size={20} />
            <span className="whitespace-nowrap">Cases</span>
          </NavLink>
          {showScanner && (
            <NavLink
              to="/scan"
              className={({isActive}) => `flex shrink-0 items-center gap-2 px-3 py-2.5 rounded-lg text-sm transition-all md:gap-3 md:px-4 md:py-3 md:text-base ${isActive ? 'bg-primary/10 text-primary font-medium shadow-[inset_0_-2px_0_0_currentColor] md:shadow-[inset_2px_0_0_0_currentColor]' : 'text-slate-300 hover:bg-white/5 hover:text-white'}`}
            >
              <Scan size={20} />
              <span className="whitespace-nowrap">Scanner</span>
            </NavLink>
          )}
          {showAudit && (
            <NavLink
              to="/audit"
              className={({isActive}) => `flex shrink-0 items-center gap-2 px-3 py-2.5 rounded-lg text-sm transition-all md:gap-3 md:px-4 md:py-3 md:text-base ${isActive ? 'bg-primary/10 text-primary font-medium shadow-[inset_0_-2px_0_0_currentColor] md:shadow-[inset_2px_0_0_0_currentColor]' : 'text-slate-300 hover:bg-white/5 hover:text-white'}`}
            >
              <ScrollText size={20} />
              <span className="whitespace-nowrap">Audit</span>
            </NavLink>
          )}
        </nav>
      </div>

      <div className="flex items-center gap-2 border-t border-slate-700/50 p-3 sm:p-4 md:block">
        <div className="mb-0 flex min-w-0 flex-1 items-center gap-3 rounded-lg bg-black/20 px-3 py-2.5 md:mb-2 md:px-4 md:py-3">
          <div className="bg-slate-700 rounded-full p-1">
            <User size={16} className="text-slate-300" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-white truncate">{username}</p>
            <p className="text-xs text-slate-400 uppercase tracking-wider">{role}</p>
          </div>
        </div>
        <button
          onClick={handleLogout}
          aria-label="Sign out"
          className="flex shrink-0 items-center justify-center gap-2 rounded-lg px-3 py-2.5 text-sm text-slate-400 transition-all hover:bg-danger/10 hover:text-danger md:w-full md:justify-start md:gap-3 md:px-4 md:py-3 md:text-base"
        >
          <LogOut size={20} />
          <span className="hidden sm:inline">Sign Out</span>
        </button>
      </div>
    </aside>
  );
}
