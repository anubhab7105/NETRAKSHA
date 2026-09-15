import React, { useState, useEffect, useCallback } from 'react';
import { Loader2, Search, ChevronLeft, ChevronRight, ShieldCheck, AlertTriangle } from 'lucide-react';
import api from '../api';
import SEO from '../components/SEO';
import Breadcrumbs from '../components/Breadcrumbs';
import { PageHeader } from '../components/ui';

export default function AuditTrail() {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actorFilter, setActorFilter] = useState('');
  const [entityFilter, setEntityFilter] = useState('');
  const [offset, setOffset] = useState(0);
  const [count, setCount] = useState(0);
  const [verifyResult, setVerifyResult] = useState(null);
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

  const handleVerify = async () => {
    try {
      const res = await api.get('/audit/verify');
      setVerifyResult(res.data);
    } catch (err) {
      setVerifyResult({ valid: false, reason: err.response?.data?.detail || 'Verification failed' });
    }
  };

  return (
    <div className="animate-fade-in space-y-5">
      <SEO
        title="Audit Trail"
        description="Immutable, append-only event ledger of every automated screening check, officer decision and override across the Netraksha system."
        path="/audit"
      />
      <Breadcrumbs items={[{ label: 'Overview', to: '/' }, { label: 'Audit Logs' }]} />
      <PageHeader
        title="Audit Logs"
        subtitle="Immutable event ledger — every automated check and officer decision. Hash-chained for tamper evidence."
        actions={
          <button onClick={handleVerify} className="gov-btn gov-btn-secondary">
            <ShieldCheck size={16} aria-hidden="true" /> Verify Chain
          </button>
        }
      />

      {verifyResult && (
        <div className={`gov-notice ${verifyResult.valid ? 'gov-notice-green' : 'gov-notice-red'}`} role="status">
          {verifyResult.valid
            ? <ShieldCheck size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
            : <AlertTriangle size={18} className="mt-0.5 shrink-0" aria-hidden="true" />}
          <span>
            {verifyResult.valid
              ? `Chain verified — ${verifyResult.total_entries} entries, last ${String(verifyResult.last_hash).slice(0, 8)}…`
              : `Chain broken at #${verifyResult.first_broken_id}: ${verifyResult.reason || ''}`}
          </span>
        </div>
      )}

      {/* Filters */}
      <form onSubmit={handleSearch} className="gov-card-padded flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
        <div className="min-w-0 flex-1 sm:min-w-[200px]">
          <label htmlFor="audit-actor" className="gov-label !mb-1 !text-[13px]">Actor</label>
          <input
            id="audit-actor"
            type="text"
            value={actorFilter}
            onChange={(e) => setActorFilter(e.target.value)}
            placeholder="Filter by officer username"
            className="gov-input"
          />
        </div>
        <div className="min-w-0 flex-1 sm:min-w-[200px]">
          <label htmlFor="audit-entity" className="gov-label !mb-1 !text-[13px]">Entity</label>
          <input
            id="audit-entity"
            type="text"
            value={entityFilter}
            onChange={(e) => setEntityFilter(e.target.value)}
            placeholder="e.g. case:12"
            className="gov-input"
          />
        </div>
        <button
          type="submit"
          className="gov-btn gov-btn-primary"
        >
          <Search size={16} aria-hidden="true" /> Apply Filters
        </button>
      </form>

      {/* Table */}
      <div className="gov-table-wrap">
        {loading ? (
          <div className="flex items-center justify-center p-12 text-[#667085]">
            <Loader2 className="mr-2 animate-spin" size={20} aria-hidden="true" />
            Loading audit logs…
          </div>
        ) : logs.length === 0 ? (
          <div className="p-12 text-center text-[#667085]">
            No audit entries found.
          </div>
        ) : (
          <div className="gov-table-scroll">
            <table className="gov-table min-w-[720px]">
              <thead>
                <tr>
                  <th scope="col">ID</th>
                  <th scope="col">Timestamp</th>
                  <th scope="col">Actor</th>
                  <th scope="col">Action</th>
                  <th scope="col">Entity</th>
                  <th scope="col">Hash</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr key={log.id}>
                    <td className="font-mono text-xs text-[#98A2B3]">{log.id}</td>
                    <td className="text-xs whitespace-nowrap">{log.timestamp ? new Date(log.timestamp).toLocaleString('en-IN') : '-'}</td>
                    <td>
                      <span className={`gov-badge ${log.actor === 'system' ? 'gov-badge-blue' : 'gov-badge-grey'}`}>
                        {log.actor}
                      </span>
                    </td>
                    <td className="font-mono text-xs">{log.action}</td>
                    <td className="font-mono text-xs text-[#667085]">{log.entity || '-'}</td>
                    <td className="font-mono text-[11px] text-[#98A2B3]" title={`${log.prev_hash} → ${log.entry_hash}`}>{log.entry_hash ? `${String(log.entry_hash).slice(0, 8)}…` : '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {!loading && count > 0 && (
          <div className="flex flex-col gap-3 border-t border-[#D9DEE7] bg-[#F7F8FA] px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <span className="text-xs text-[#667085]">
              Showing {offset + 1}–{Math.min(offset + limit, offset + count)} entries
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => setOffset(Math.max(0, offset - limit))}
                disabled={offset === 0}
                aria-label="Previous page"
                className="gov-icon-btn !h-8 !w-8 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <ChevronLeft size={16} aria-hidden="true" />
              </button>
              <button
                onClick={() => setOffset(offset + limit)}
                disabled={count < limit}
                aria-label="Next page"
                className="gov-icon-btn !h-8 !w-8 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <ChevronRight size={16} aria-hidden="true" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
