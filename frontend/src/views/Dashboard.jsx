import React, { useState, useEffect, useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  RefreshCw, Search, ShieldCheck, CheckCircle2, AlertTriangle,
  FileText, ChevronRight, ClipboardList, ScanLine, BellRing,
} from 'lucide-react';
import api from '../api';
import SEO from '../components/SEO';
import { PageHeader, KpiCard, VerdictBadge } from '../components/ui';

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
  const [query, setQuery] = useState('');
  const navigate = useNavigate();

  const fetchCases = async () => {
    setLoading(true);
    try {
      const res = await api.get('/cases');
      const payload = res.data;
      const list = Array.isArray(payload?.cases) ? payload.cases : Array.isArray(payload) ? payload : [];
      setCases(list);
    } catch (e) {
      if (import.meta.env.DEV) console.error(e);
      // keep existing cases on error; don't set undefined
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCases();
  }, []);

  const safeCases = Array.isArray(cases) ? cases : [];

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
            <Link to="/scan" className="gov-btn gov-btn-secondary">
              <ScanLine size={16} aria-hidden="true" /> New Verification
            </Link>
            <button onClick={fetchCases} aria-label="Refresh case list" className="gov-icon-btn" title="Refresh case list">
              <RefreshCw size={18} className={loading ? 'animate-spin' : ''} aria-hidden="true" />
            </button>
          </>
        }
      />

      {/* KPI cards */}
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

      {/* Case queue */}
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
                  <td colSpan="6" className="!py-12 text-center text-[#667085]">Loading cases…</td>
                </tr>
              ) : filteredCases.length === 0 ? (
                <tr>
                  <td colSpan="6" className="!py-12 text-center text-[#667085]">
                    {safeCases.length === 0 ? (
                      <>No cases yet. <Link to="/scan" className="font-semibold text-[#1769AA] hover:underline">Start a screening</Link> from New Verification.</>
                    ) : (
                      'No cases match your search.'
                    )}
                  </td>
                </tr>
              ) : (
                filteredCases.map((c) => (
                  <tr
                    key={c.id}
                    className="group cursor-pointer"
                    onClick={() => navigate(`/case/${c.id}`)}
                    onKeyDown={(e) => { if (e.key === 'Enter') navigate(`/case/${c.id}`); }}
                    tabIndex={0}
                    aria-label={`Open case ${c.id.toString().padStart(4, '0')}`}
                  >
                    <td className="font-semibold text-[#123B66]">#{c.id.toString().padStart(4, '0')}</td>
                    <td>
                      <span className="block text-sm text-[#172033]">{new Date(c.timestamp).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}</span>
                      <span className="block text-xs text-[#98A2B3]">{new Date(c.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}</span>
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
                      <span className="inline-flex items-center gap-1 text-[13px] font-semibold text-[#98A2B3] group-hover:text-[#123B66]">
                        Open <ChevronRight size={16} aria-hidden="true" />
                      </span>
                    </td>
                  </tr>
                ))
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
