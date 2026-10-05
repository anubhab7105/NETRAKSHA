import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  RefreshCw, Search, ShieldCheck, CheckCircle2, AlertTriangle,
  FileText, ChevronRight, ClipboardList, ScanLine, BellRing,
} from 'lucide-react';
import api, { apiErrorMessage } from '../api';
import SEO from '../components/SEO';
import { PageHeader, KpiCard, VerdictBadge } from '../components/ui';

function formatCaseDate(value) {
  if (!value) return { date: '—', time: '' };
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return { date: 'Invalid date', time: '' };
  return {
    date: d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }),
    time: d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }),
  };
}

function formatCaseId(id) {
  const n = Number(id);
  if (!Number.isFinite(n)) return '#—';
  return `#${Math.trunc(n).toString().padStart(4, '0')}`;
}

const StatusText = ({ status }) => {
  const pending = status !== 'decided';
  return (
    <span className={`text-xs font-semibold uppercase tracking-[0.05em] ${pending ? 'text-[#1769AA]' : 'text-[#98A2B3]'}`}>
      {String(status || '').replace('_', ' ')}
    </span>
  );
};

export default function Dashboard() {
  const [cases, setCases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState('');
  const [query, setQuery] = useState('');
  const navigate = useNavigate();
  const role = (localStorage.getItem('role') || '').toLowerCase();
  const canScan = role === 'officer' || role === 'supervisor';

  const fetchCases = useCallback(async (signal) => {
    setLoading(true);
    setFetchError('');
    try {
      const res = await api.get('/cases', { signal });
      const payload = res.data;
      const list = Array.isArray(payload?.cases) ? payload.cases : Array.isArray(payload) ? payload : [];
      if (signal?.aborted) return;
      setCases(list);
    } catch (e) {
      if (signal?.aborted) return;
      if (import.meta.env.DEV) console.error(e);
      setFetchError(apiErrorMessage(e, 'Could not load cases.'));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Deferred (like AuditTrail's debounced fetch) so mount-time state updates
    // run asynchronously — never as synchronous setState inside the effect.
    const controller = new AbortController();
    const timer = setTimeout(() => fetchCases(controller.signal), 0);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [fetchCases]);

  const safeCases = useMemo(() => (Array.isArray(cases) ? cases : []), [cases]);

  const filteredCases = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return safeCases;
    return safeCases.filter((c) => {
      const id = (c?.id ?? 0).toString().padStart(4, '0');
      const type = (c.document_type || '').toLowerCase();
      return id.includes(q.replace(/^#/, '')) || type.includes(q);
    });
  }, [safeCases, query]);

  const stats = useMemo(() => {
    const total = safeCases.length;
    const verified = safeCases.filter((c) => c.verdict === 'Green').length;
    const review = safeCases.filter((c) => c.verdict === 'Yellow').length;
    const flagged = safeCases.filter((c) => c.verdict === 'Red').length;
    const pending = safeCases.filter((c) => c.status !== 'decided').length;
    return { total, verified, review, flagged, pending };
  }, [safeCases]);

  return (
    <div className="animate-fade-in space-y-6">
      <SEO
        title="Case Dashboard"
        description="Monitor and adjudicate identity screening cases: composite Green/Yellow/Red risk verdicts, review status and per-case forensic reports."
        path="/"
      />
      <PageHeader
        title="Operations Overview"
        subtitle="Monitor verifications, triage the case queue and adjudicate screenings."
        actions={
          <>
            {canScan && (
            <Link to="/scan" className="gov-btn gov-btn-secondary">
              <ScanLine size={16} aria-hidden="true" /> New Verification
            </Link>
            )}
            <button onClick={() => fetchCases()} aria-label="Refresh case list" className="gov-icon-btn" title="Refresh case list">
              <RefreshCw size={18} className={loading ? 'animate-spin' : ''} aria-hidden="true" />
            </button>
          </>
        }
      />

      {fetchError && (
        <div className="gov-notice gov-notice-red" role="alert">
          <AlertTriangle size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span className="flex-1">{fetchError}</span>
          <button onClick={() => fetchCases()} className="gov-btn gov-btn-secondary shrink-0">
            <RefreshCw size={14} aria-hidden="true" /> Retry
          </button>
        </div>
      )}

      {}
      <section aria-label="Verification summary" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Total Verifications"
          value={loading ? '—' : stats.total}
          sub={`${stats.pending} awaiting decision`}
          accent="#123B66"
          icon={<ClipboardList size={20} aria-hidden="true" />}
        />
        <KpiCard
          label="Verified"
          value={loading ? '—' : stats.verified}
          sub="Low-risk outcomes"
          accent="#16803C"
          icon={<CheckCircle2 size={20} aria-hidden="true" />}
        />
        <KpiCard
          label="Manual Review"
          value={loading ? '—' : stats.review}
          sub="Officer review required"
          accent="#B7791F"
          icon={<AlertTriangle size={20} aria-hidden="true" />}
        />
        <KpiCard
          label="Flagged"
          value={loading ? '—' : stats.flagged}
          sub="High-risk · escalate"
          accent="#C62828"
          icon={<ShieldCheck size={20} aria-hidden="true" />}
        />
      </section>

      {}
      <section aria-label="Case queue" className="gov-table-wrap">
        <div className="flex flex-col gap-3 border-b border-[#D9DEE7] p-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="gov-card-title">Case Queue</h2>
            <p className="gov-meta mt-0.5">
              {filteredCases.length} of {safeCases.length} cases · select a row to open the full report
            </p>
          </div>
          <div className="relative w-full sm:max-w-[320px]">
            <Search className="absolute top-1/2 left-3 -translate-y-1/2 text-[#98A2B3]" size={17} aria-hidden="true" />
            <input
              type="search"
              aria-label="Search cases"
              placeholder="Search by case ID or document type…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="gov-input gov-input-with-icon"
            />
          </div>
        </div>

        <div className="gov-table-scroll">
          <table className="gov-table min-w-[760px]">
            <thead>
              <tr>
                <th scope="col">Case ID</th>
                <th scope="col">Applicant / Timestamp</th>
                <th scope="col">Document</th>
                <th scope="col">Verdict</th>
                <th scope="col">Status</th>
                <th scope="col"><span className="sr-only">Open case</span></th>
              </tr>
            </thead>
            <tbody>
              {loading && safeCases.length === 0 ? (
                <tr>
                  <td colSpan="6" className="py-12! text-center text-[#667085]">Loading cases…</td>
                </tr>
              ) : filteredCases.length === 0 ? (
                <tr>
                  <td colSpan="6" className="py-12! text-center text-[#667085]">
                    {safeCases.length === 0 ? (
                      canScan
                        ? (<>No cases yet. <Link to="/scan" className="font-semibold text-[#1769AA] hover:underline">Start a screening</Link> from New Verification.</>)
                        : 'No cases yet.'
                    ) : (
                      'No cases match your search.'
                    )}
                  </td>
                </tr>
              ) : (
                filteredCases.map((c) => {
                  const { date, time } = formatCaseDate(c.timestamp);
                  const label = `Open case ${formatCaseId(c.id)}`;
                  return (
                  <tr
                    key={c.id}
                    className="group cursor-pointer"
                    tabIndex={0}
                    aria-label={label}
                    onClick={() => navigate(`/case/${c.id}`)}
                    onKeyDown={(e) => { if (e.key === 'Enter') navigate(`/case/${c.id}`); }}
                  >
                    <td className="font-semibold text-[#123B66]">
                      <Link to={`/case/${c.id}`} aria-label={label} onClick={(e) => e.stopPropagation()} className="rounded hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1769AA]">
                        {formatCaseId(c.id)}
                      </Link>
                    </td>
                    <td>
                      <span className="block text-sm text-[#172033]">{date}</span>
                      <span className="block text-xs text-[#98A2B3]">{time}</span>
                    </td>
                    <td>
                      <span className="gov-badge gov-badge-grey">
                        <FileText size={12} aria-hidden="true" />
                        {c.document_type ? c.document_type.toUpperCase() : 'UNKNOWN'}
                      </span>
                    </td>
                    <td>
                      <VerdictBadge verdict={c.verdict} />
                    </td>
                    <td>
                      <StatusText status={c.status} />
                    </td>
                    <td className="text-right">
                      <Link to={`/case/${c.id}`} aria-label={label} onClick={(e) => e.stopPropagation()} className="inline-flex items-center gap-1 rounded text-[13px] font-semibold text-[#98A2B3] group-hover:text-[#123B66] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1769AA]">
                        Open <ChevronRight size={16} aria-hidden="true" />
                      </Link>
                    </td>
                  </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        <div className="flex items-center gap-2 border-t border-[#D9DEE7] bg-[#F7F8FA] px-4 py-2.5">
          <BellRing size={14} className="text-[#98A2B3]" aria-hidden="true" />
          <p className="text-xs text-[#667085]">
            High-risk verdicts stay at the top of the review priority. All decisions require a written justification.
          </p>
        </div>
      </section>
    </div>
  );
}
