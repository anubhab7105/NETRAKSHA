import React, { useState, useEffect, useCallback } from 'react';
import { Loader2, ScrollText, Search, ChevronLeft, ChevronRight } from 'lucide-react';
import api from '../api';
import SEO from '../components/SEO';
import Breadcrumbs from '../components/Breadcrumbs';

export default function AuditTrail() {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actorFilter, setActorFilter] = useState('');
  const [entityFilter, setEntityFilter] = useState('');
  const [offset, setOffset] = useState(0);
  const [count, setCount] = useState(0);
  const limit = 50;

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit, offset };
      if (actorFilter.trim()) params.actor = actorFilter.trim();
      if (entityFilter.trim()) params.entity = entityFilter.trim();
      const res = await api.get('/audit', { params });
      setLogs(res.data.audit_logs || []);
      setCount(res.data.count || 0);
    } catch (err) {
      if (import.meta.env.DEV) console.error('Failed to fetch audit logs:', err);
    } finally {
      setLoading(false);
    }
  }, [offset, actorFilter, entityFilter]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  const handleSearch = (e) => {
    e.preventDefault();
    setOffset(0);
    fetchLogs();
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <SEO
        title="Audit Trail"
        description="Immutable, append-only event ledger of every automated screening check, officer decision and override across the SSB Sentinel system."
        path="/audit"
      />
      <Breadcrumbs items={[{ label: 'Home', to: '/' }, { label: 'Audit Trail' }]} />
      <header>
        <h1 className="text-2xl font-bold text-white flex items-center gap-3">
          <div className="bg-primary/20 p-2 rounded-lg text-primary">
            <ScrollText size={24} />
          </div>
          Audit Trail
        </h1>
        <p className="text-slate-400 text-sm mt-1">
          Immutable event ledger — every automated check and officer decision.
        </p>
      </header>

      {/* Filters */}
      <form onSubmit={handleSearch} className="glass-panel flex flex-col gap-4 p-4 sm:flex-row sm:flex-wrap sm:items-end">
        <div className="min-w-0 flex-1 sm:min-w-[200px]">
          <label htmlFor="audit-actor" className="block text-xs font-medium text-slate-400 mb-1">Actor</label>
          <input
            id="audit-actor"
            type="text"
            value={actorFilter}
            onChange={(e) => setActorFilter(e.target.value)}
            placeholder="Filter by officer username"
            className="w-full bg-black/30 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-primary transition-colors"
          />
        </div>
        <div className="min-w-0 flex-1 sm:min-w-[200px]">
          <label htmlFor="audit-entity" className="block text-xs font-medium text-slate-400 mb-1">Entity</label>
          <input
            id="audit-entity"
            type="text"
            value={entityFilter}
            onChange={(e) => setEntityFilter(e.target.value)}
            placeholder="e.g. case:12"
            className="w-full bg-black/30 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-primary transition-colors"
          />
        </div>
        <button
          type="submit"
          className="flex items-center justify-center gap-2 rounded-lg border border-primary/30 bg-primary/10 px-4 py-2 text-sm font-medium text-primary transition-colors hover:bg-primary/20"
        >
          <Search size={16} /> Filter
        </button>
      </form>

      {/* Table */}
      <div className="glass-panel overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center p-12 text-slate-400">
            <Loader2 className="animate-spin mr-2" size={20} />
            Loading audit logs...
          </div>
        ) : logs.length === 0 ? (
          <div className="text-center p-12 text-slate-500">
            No audit entries found.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-700/50 bg-black/20">
                  <th className="px-6 py-3 font-medium">ID</th>
                  <th className="px-6 py-3 font-medium">Timestamp</th>
                  <th className="px-6 py-3 font-medium">Actor</th>
                  <th className="px-6 py-3 font-medium">Action</th>
                  <th className="px-6 py-3 font-medium">Entity</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/30">
                {logs.map((log) => (
                  <tr key={log.id} className="text-slate-300 hover:bg-white/5 transition-colors">
                    <td className="px-6 py-3 font-mono text-xs text-slate-500">{log.id}</td>
                    <td className="px-6 py-3 text-xs">{log.timestamp ? new Date(log.timestamp).toLocaleString() : '-'}</td>
                    <td className="px-6 py-3">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${log.actor === 'system' ? 'bg-primary/10 text-primary' : 'bg-slate-800 text-slate-200'}`}>
                        {log.actor}
                      </span>
                    </td>
                    <td className="px-6 py-3 font-mono text-xs">{log.action}</td>
                    <td className="px-6 py-3 font-mono text-xs text-slate-400">{log.entity || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {!loading && count > 0 && (
          <div className="flex flex-col gap-3 border-t border-slate-700/50 bg-black/10 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <span className="text-xs text-slate-500">
              Showing {offset + 1}–{Math.min(offset + limit, offset + count)} entries
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => setOffset(Math.max(0, offset - limit))}
                disabled={offset === 0}
                aria-label="Previous page"
                className="p-1.5 rounded text-slate-400 hover:text-white hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronLeft size={16} />
              </button>
              <button
                onClick={() => setOffset(offset + limit)}
                disabled={count < limit}
                aria-label="Next page"
                className="p-1.5 rounded text-slate-400 hover:text-white hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
