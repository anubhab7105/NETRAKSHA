import React from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
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
    <aside className="w-64 bg-surface/50 border-r border-slate-700/50 backdrop-blur-xl flex flex-col justify-between z-20">
      <div>
        <div className="p-6 flex items-center gap-3 border-b border-slate-700/50">
          <div className="bg-primary/20 p-2 rounded-lg text-primary">
            <Shield size={24} />
          </div>
          <div>
            <h1 className="text-lg font-bold bg-clip-text text-transparent bg-gradient-to-r from-primary to-accent">SSB Sentinel</h1>
            <p className="text-xs text-slate-400">Identity Screening</p>
          </div>
        </div>
        
        <nav className="p-4 space-y-2">
          <NavLink
            to="/"
            className={({isActive}) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-all ${isActive ? 'bg-primary/10 text-primary font-medium shadow-[inset_2px_0_0_0_currentColor]' : 'text-slate-300 hover:bg-white/5 hover:text-white'}`}
          >
            <List size={20} />
            Case Dashboard
          </NavLink>
          {showScanner && (
            <NavLink
              to="/scan"
              className={({isActive}) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-all ${isActive ? 'bg-primary/10 text-primary font-medium shadow-[inset_2px_0_0_0_currentColor]' : 'text-slate-300 hover:bg-white/5 hover:text-white'}`}
            >
              <Scan size={20} />
              Kiosk Scanner
            </NavLink>
          )}
          {showAudit && (
            <NavLink
              to="/audit"
              className={({isActive}) => `flex items-center gap-3 px-4 py-3 rounded-lg transition-all ${isActive ? 'bg-primary/10 text-primary font-medium shadow-[inset_2px_0_0_0_currentColor]' : 'text-slate-300 hover:bg-white/5 hover:text-white'}`}
            >
              <ScrollText size={20} />
              Audit Trail
            </NavLink>
          )}
        </nav>
      </div>

      <div className="p-4 border-t border-slate-700/50">
        <div className="flex items-center gap-3 px-4 py-3 mb-2 rounded-lg bg-black/20">
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
          className="w-full flex items-center gap-3 px-4 py-3 rounded-lg text-slate-400 hover:bg-danger/10 hover:text-danger transition-all"
        >
          <LogOut size={20} />
          Sign Out
        </button>
      </div>
    </aside>
  );
}
