import React from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { LayoutDashboard, ScanLine, ScrollText, LogOut, UserRound, ShieldCheck } from 'lucide-react';
import api from '../api';

export default function Sidebar() {
  const navigate = useNavigate();
  const role = localStorage.getItem('role') || 'officer';
  const username = localStorage.getItem('username') || 'Unknown';

  const handleLogout = async () => {
    try {
      await api.post('/auth/logout');
    } catch (e) {
      
    }
    localStorage.clear();
    navigate('/login');
  };

  
  
  
  
  const showScanner = role === 'officer' || role === 'supervisor';
  const showAudit = role === 'supervisor' || role === 'auditor';

  const linkCls = ({ isActive }) =>
    `gov-nav-link ${isActive ? 'gov-nav-link-active' : ''}`;

  return (
    <aside className="z-20 flex w-full shrink-0 flex-col justify-between border-b border-[#D9DEE7] bg-white md:h-full md:w-60 md:border-b-0 md:border-r">
      <div className="min-w-0">
        <Link
          to="/"
          className="flex items-center gap-3 border-b border-[#D9DEE7] p-4"
          aria-label="Netraksha — go to Case Dashboard"
        >
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#123B66] text-white" aria-hidden="true">
            <ShieldCheck size={20} />
          </div>
          <div className="min-w-0 leading-tight">
            <p className="text-[15px] font-bold text-[#123B66]">NETRAKSHA</p>
            <p className="text-[11px] font-medium uppercase tracking-[0.06em] text-[#667085]">
              Identity Verification
            </p>
          </div>
        </Link>

        <nav aria-label="Primary navigation" className="flex gap-1 overflow-x-auto p-3 md:block md:space-y-1 md:overflow-visible">
          <p className="mb-1 hidden px-2 text-[11px] font-semibold uppercase tracking-[0.07em] text-[#98A2B3] md:block">
            Operations
          </p>
          <NavLink to="/" end className={linkCls}>
            <LayoutDashboard size={18} aria-hidden="true" />
            <span className="whitespace-nowrap">Overview</span>
          </NavLink>
          {showScanner && (
            <NavLink to="/scan" className={linkCls}>
              <ScanLine size={18} aria-hidden="true" />
              <span className="whitespace-nowrap">New Verification</span>
            </NavLink>
          )}
          {showAudit && (
            <NavLink to="/audit" className={linkCls}>
              <ScrollText size={18} aria-hidden="true" />
              <span className="whitespace-nowrap">Audit Logs</span>
            </NavLink>
          )}
          <p className="mt-3 hidden px-2 text-[11px] font-medium leading-relaxed text-[#98A2B3] md:block">
            Case queue, alerts and reports are reviewed from the Overview dashboard.
          </p>
        </nav>
      </div>

      <div className="flex items-center gap-2 border-t border-[#D9DEE7] bg-[#F7F8FA] p-3 md:block">
        <div className="flex min-w-0 flex-1 items-center gap-3 rounded-lg border border-[#D9DEE7] bg-white px-3 py-2.5 md:mb-2">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#E8F1FA] text-[#123B66]" aria-hidden="true">
            <UserRound size={16} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-[#172033]">{username}</p>
            <p className="text-[11px] font-medium uppercase tracking-[0.07em] text-[#667085]">{role}</p>
          </div>
        </div>
        <button
          onClick={handleLogout}
          aria-label="Sign out"
          className="gov-btn gov-btn-ghost shrink-0 !px-3 md:w-full md:justify-start"
        >
          <LogOut size={18} aria-hidden="true" />
          <span className="hidden sm:inline">Sign Out</span>
        </button>
      </div>
    </aside>
  );
}
