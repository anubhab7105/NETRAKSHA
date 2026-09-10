import React, { useState, useEffect, useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { RefreshCw, Search, ShieldAlert, CheckCircle, AlertTriangle, FileText, ChevronRight } from 'lucide-react';
import api from '../api';
import SEO from '../components/SEO';

const VerdictBadge = ({ verdict }) => {
  const styles = {
    Green: 'bg-success/10 text-success border-success/30',
    Yellow: 'bg-warning/10 text-warning border-warning/30',
    Red: 'bg-danger/10 text-danger border-danger/30',
  };
  const icons = {
    Green: <CheckCircle size={14} />,
    Yellow: <AlertTriangle size={14} />,
    Red: <ShieldAlert size={14} />
  };
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${styles[verdict] || 'bg-slate-800 text-slate-300 border-slate-700'}`}>
      {icons[verdict]}
      {verdict}
    </span>
  );
};

export default function Dashboard() {
  const [cases, setCases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const navigate = useNavigate();

  const fetchCases = async () => {
    setLoading(true);
    try {
      const res = await api.get('/cases');
      setCases(res.data.cases);
    } catch (e) {
      if (import.meta.env.DEV) console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCases();
  }, []);

  const filteredCases = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return cases;
    return cases.filter((c) => {
      const id = c.id.toString().padStart(4, '0');
      const type = (c.document_type || '').toLowerCase();
      return id.includes(q.replace(/^#/, '')) || type.includes(q);
    });
  }, [cases, query]);

  return (
    <div className="space-y-6 animate-fade-in">
      <SEO
        title="Case Dashboard"
        description="Monitor and adjudicate identity screening cases: composite Green/Yellow/Red risk verdicts, review status and per-case forensic reports."
        path="/"
      />
      <header className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Case Dashboard</h1>
          <p className="text-slate-400 text-sm mt-1">Monitor and adjudicate recent screenings.</p>
        </div>
        <button onClick={fetchCases} aria-label="Refresh case list" className="inline-flex w-full items-center justify-center rounded-lg border border-slate-700 bg-surface p-2 text-slate-300 transition-colors hover:bg-slate-700/50 sm:w-auto">
          <RefreshCw size={20} className={loading ? "animate-spin" : ""} />
        </button>
      </header>

      <div className="glass-panel overflow-hidden">
        <div className="flex gap-4 border-b border-slate-700/50 p-4">
          <div className="relative w-full sm:max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" size={18} />
            <input
              type="search"
              aria-label="Search cases"
              placeholder="Search by case ID or document type..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full bg-black/20 border border-slate-700 rounded-lg pl-10 pr-4 py-2 text-sm text-white focus:outline-none focus:border-primary transition-colors"
            />
          </div>
        </div>
        
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-collapse text-left">
            <thead>
              <tr className="bg-black/20 text-slate-400 text-xs uppercase tracking-wider">
                <th className="px-6 py-4 font-medium">Case ID</th>
                <th className="px-6 py-4 font-medium">Timestamp</th>
                <th className="px-6 py-4 font-medium">Document Type</th>
                <th className="px-6 py-4 font-medium">Verdict</th>
                <th className="px-6 py-4 font-medium">Status</th>
                <th className="px-6 py-4 font-medium text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {loading && cases.length === 0 ? (
                <tr>
                  <td colSpan="6" className="px-6 py-12 text-center text-slate-500">Loading cases...</td>
                </tr>
              ) : filteredCases.length === 0 ? (
                <tr>
                  <td colSpan="6" className="px-6 py-12 text-center text-slate-500">
                    {cases.length === 0 ? (
                      <>No cases yet. <Link to="/scan" className="text-primary hover:underline">Start a screening</Link> from the kiosk scanner.</>
                    ) : (
                      'No cases match your search.'
                    )}
                  </td>
                </tr>
              ) : (
                filteredCases.map((c) => (
                  <tr key={c.id} className="hover:bg-white/5 transition-colors group cursor-pointer" onClick={() => navigate(`/case/${c.id}`)}>
                    <td className="px-6 py-4 text-sm font-medium text-slate-300">#{c.id.toString().padStart(4, '0')}</td>
                    <td className="px-6 py-4 text-sm text-slate-400">{new Date(c.timestamp).toLocaleString()}</td>
                    <td className="px-6 py-4">
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-800 text-slate-300 text-xs border border-slate-700">
                        <FileText size={12} />
                        {c.document_type ? c.document_type.toUpperCase() : 'UNKNOWN'}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <VerdictBadge verdict={c.verdict} />
                    </td>
                    <td className="px-6 py-4">
                      <span className={`text-xs font-medium uppercase tracking-wider ${c.status === 'decided' ? 'text-slate-500' : 'text-primary'}`}>
                        {c.status.replace('_', ' ')}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-right">
                      <button aria-label={`Open case #${c.id.toString().padStart(4, '0')}`} className="text-slate-400 group-hover:text-white transition-colors">
                        <ChevronRight size={20} />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
