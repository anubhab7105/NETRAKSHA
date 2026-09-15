import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ShieldAlert, CheckCircle2, AlertTriangle, ArrowLeft, Loader2, UserRound,
  FileText, Image as ImageIcon, Check, X, ShieldCheck, Activity, ScanLine,
  Eye, Fingerprint, Hash, Radio, ChevronDown,
} from 'lucide-react';
import api from '../api';
import SEO from '../components/SEO';
import Breadcrumbs from '../components/Breadcrumbs';
import { CheckRow, GovNotice, StatusBadge } from '../components/ui';

const VERDICT_META = {
  Green: {
    tone: 'green', bar: '#16803C', icon: <CheckCircle2 size={30} aria-hidden="true" />,
    title: 'VERIFIED', desc: 'All checks passed. Low risk. Recommend clearance pending officer confirmation.',
  },
  Yellow: {
    tone: 'amber', bar: '#B7791F', icon: <AlertTriangle size={30} aria-hidden="true" />,
    title: 'MANUAL REVIEW', desc: 'Anomalies detected. Manual review required by reviewing officer.',
  },
  Red: {
    tone: 'red', bar: '#C62828', icon: <ShieldAlert size={30} aria-hidden="true" />,
    title: 'HIGH RISK — ESCALATE', desc: 'Critical risk flags detected. Escalation recommended for officer review.',
  },
};

const VerdictCard = ({ verdict, riskScore, anomalyCount, similarity }) => {
  const meta = VERDICT_META[verdict] || {
    tone: 'grey', bar: '#98A2B3', icon: <ShieldAlert size={30} aria-hidden="true" />,
    title: String(verdict || 'UNKNOWN').toUpperCase(), desc: 'Unable to determine risk level.',
  };
  return (
    <section aria-label="Verification result" className="gov-card overflow-hidden">
      <div className="h-1.5" style={{ background: meta.bar }} aria-hidden="true" />
      <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:p-6">
        <div
          className="flex h-16 w-16 shrink-0 items-center justify-center rounded-xl border"
          style={{ color: meta.bar, background: `${meta.bar}14`, borderColor: `${meta.bar}45` }}
          aria-hidden="true"
        >
          {meta.icon}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-bold uppercase tracking-[0.1em] text-[#667085]">Verification Result</p>
          <h2 className="mt-0.5 flex flex-wrap items-center gap-2 text-xl font-bold text-[#172033]">
            {meta.title}
            <StatusBadge tone={meta.tone} icon={meta.icon}>{`Risk: ${verdict || 'Unknown'}`}</StatusBadge>
          </h2>
          <p className="mt-1 text-sm text-[#667085]">{meta.desc}</p>
        </div>
        {/* Stacked on phones (3-up would squeeze and overflow), 3-up from 480px, stacked again on sm where the sidebar narrows the content. */}
        <dl className="grid w-full shrink-0 grid-cols-1 gap-2 min-[480px]:grid-cols-3 sm:grid-cols-1 sm:min-w-[190px] lg:grid-cols-3 lg:min-w-[320px]">
          <div className="rounded-lg border border-[#D9DEE7] bg-[#F7F8FA] px-3 py-2 text-center">
            <dt className="text-[11px] font-semibold uppercase tracking-wide text-[#667085]">Risk Score</dt>
            <dd className="text-lg font-bold text-[#172033]">{riskScore != null ? `${Math.round(Number(riskScore))} / 100` : '—'}</dd>
          </div>
          <div className="rounded-lg border border-[#D9DEE7] bg-[#F7F8FA] px-3 py-2 text-center">
            <dt className="text-[11px] font-semibold uppercase tracking-wide text-[#667085]">Face Match</dt>
            <dd className="text-lg font-bold text-[#172033]">{similarity != null ? `${(Number(similarity) * 100).toFixed(1)}%` : 'N/A'}</dd>
          </div>
          <div className="rounded-lg border border-[#D9DEE7] bg-[#F7F8FA] px-3 py-2 text-center">
            <dt className="text-[11px] font-semibold uppercase tracking-wide text-[#667085]">Anomalies</dt>
            <dd className="text-lg font-bold text-[#172033]">{anomalyCount}</dd>
          </div>
        </dl>
      </div>
    </section>
  );
};

/** Module status indicator */
const StatusBadgeLocal = ({ status, score }) => {
  if (status === 'inconclusive') {
    return <StatusBadge tone="amber" icon={<AlertTriangle size={12} aria-hidden="true" />}>Inconclusive</StatusBadge>;
  }
  if (score !== null && score !== undefined) {
    return (
      <span className="gov-badge gov-badge-grey">
        Score: <strong>{(score * 100).toFixed(0)}%</strong>
      </span>
    );
  }
  return <StatusBadge tone="green" icon={<Check size={12} aria-hidden="true" />}>OK</StatusBadge>;
};

/** Violet badge marking mocked/simulated data — must never look like verified output */
const MockedDataBadge = ({ label = 'MOCKED DATA' }) => (
  <StatusBadge tone="violet">{label}</StatusBadge>
);

/** Mask Aadhaar numbers to XXXX-XXXX-<last4> before render (PII hygiene) */
const maskAadhaar = (fieldName, value) => {
  if (value == null || value === '') return value;
  const name = String(fieldName || '').toLowerCase();
  const isAadhaar = name.includes('aadhaar') || name.includes('uid');
  if (!isAadhaar) return value;
  const digits = String(value).replace(/\D/g, '');
  if (digits.length < 4) return value;
  return `XXXX-XXXX-${digits.slice(-4)}`;
};

/** Authenticated evidence image — fetches a short-lived signed URL */
const EvidenceImage = ({ evidenceUri, alt }) => {
  const [src, setSrc] = useState(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    if (!evidenceUri) return;
    const filename = evidenceUri.split('/').pop();
    let cancelled = false;
    const fetchToken = async () => {
      try {
        const res = await api.get(`/evidence/token/${encodeURIComponent(filename)}`);
        if (!cancelled && res.data?.token) {
          const base = (api.defaults.baseURL || '').replace(/\/+$/, '');
          setSrc(`${base}/evidence/view?token=${encodeURIComponent(res.data.token)}`);
        }
      } catch {
        if (!cancelled) setError(true);
      }
    };
    fetchToken();
    return () => { cancelled = true; };
  }, [evidenceUri]);
  if (error) return <p className="text-sm text-[#667085]">Evidence unavailable (access denied or expired).</p>;
  if (!src) return <div className="flex items-center justify-center rounded-lg border border-dashed border-[#D9DEE7] bg-[#F7F8FA] p-8 text-[#98A2B3]"><Loader2 size={24} className="animate-spin" aria-hidden="true" /></div>;
  return (
    <img
      src={src}
      alt={alt}
      className="h-auto w-full border border-[#D9DEE7] object-cover"
      onError={() => setError(true)}
    />
  );
};

function Details({ title, children, defaultOpen = false }) {
  return (
    <details className="group rounded-lg border border-[#D9DEE7] bg-white" open={defaultOpen || undefined}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-semibold text-[#123B66] hover:bg-[#F7F8FA] [&::-webkit-details-marker]:hidden">
        {title}
        <ChevronDown size={16} className="shrink-0 text-[#667085] transition-transform group-open:rotate-180" aria-hidden="true" />
      </summary>
      <div className="border-t border-[#D9DEE7] px-4 py-3">{children}</div>
    </details>
  );
}

export default function CaseReport() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState('');
  const [reason, setReason] = useState('');
  const [provenance, setProvenance] = useState(null);
  const [provVerified, setProvVerified] = useState(null);
  const caseLabel = `Case #${(id ?? '').toString().padStart(4, '0')}`;

  useEffect(() => {
    const fetchCase = async () => {
      try {
        const res = await api.get(`/cases/${id}`);
        setData(res.data);
        // Fetch provenance for reproducibility
        try {
          const provRes = await api.get(`/cases/${id}/provenance`);
          setProvenance(provRes.data);
          setProvVerified(provRes.data.verified);
        } catch {
          // no provenance for old cases
        }
      } catch (err) {
        if (import.meta.env.DEV) console.error(err);
      } finally {
        setLoading(false);
      }
    };
    fetchCase();
  }, [id]);

  const handleAction = async (action) => {
    if (reason.length < 3) {
      setActionError('Please provide a justification (minimum 3 characters) before submitting a decision.');
      return;
    }
    setActionError('');
    setActionLoading(true);
    try {
      await api.post(`/cases/${id}/override`, { action, reason, version: data?.case?.version }, {
        headers: data?.case?.version != null ? { 'If-Match': String(data.case.version) } : {}
      });
      navigate('/');
    } catch (err) {
      const detail = err.response?.data?.detail || '';
      const status = err.response?.status;
      if (status === 409) {
        setActionError(detail || 'This case was modified by another officer. Please refresh the page and try again.');
      } else if (status === 403 && detail.toLowerCase().includes('supervisor')) {
        setActionError(detail + ' — use Escalate instead.');
      } else if (detail) {
        setActionError(detail);
      } else {
        setActionError('Failed to submit the decision. Check your connection and try again.');
      }
      setActionLoading(false);
    }
  };

  if (loading) {
    return <div className="flex h-64 items-center justify-center text-[#667085]"><Loader2 className="mr-2 animate-spin" aria-hidden="true" /> Loading case report…</div>;
  }

  if (!data || !data.case) {
    return <div className="mt-10 text-center font-semibold text-[#C62828]">Case not found.</div>;
  }

  const { case: c, extracted_fields, module_results } = data;

  // Find specific modules (audit P2 §5: render ALL)
  const findModule = (name) => module_results.find(m => m.module_name === name);
  const geminiModule = findModule('gemini_ai');
  const tamperModule = findModule('tamper');
  const physicalModule = findModule('physical_forgery');
  const deepfakeModule = findModule('deepfake');
  const livenessModule = findModule('liveness');
  const checksumModule = findModule('checksum');
  const watchlistModule = findModule('watchlist');
  const irisModule = findModule('iris');

  const geminiData = geminiModule?.raw_output || {};
  const faceMatch = geminiData.three_way_face_match || {};
  // The cloud AI payload also carries the evidence-backed local InsightFace
  // pairs (pair_sources "local"/"local_late"). When the cloud was offline the
  // module is mocked, but those local pairs are still real biometrics and must
  // be displayed — not hidden behind the "AI unavailable" notice.
  const pairSources = faceMatch.pair_sources || {};
  const hasLocalFacePair = Object.values(pairSources).some(
    (s) => typeof s === 'string' && s.startsWith('local')
  );
  const hasRealFaceVerdict =
    faceMatch.similarity_score != null ||
    faceMatch.live_vs_doc_match != null ||
    faceMatch.doc_vs_db_match != null ||
    faceMatch.live_vs_db_match != null ||
    hasLocalFacePair;
  // Registry-leg failure reasons, in officer-actionable words.
  const dbPairsReasonText = (reason) => ({
    no_registry_match: 'no matching record in the citizens registry',
    no_registry_photo: 'no reference photo on the matched record',
    registry_photo_missing_on_server: 'reference photo file missing on the server — restore it or re-enroll the photo',
    registry_photo_download_failed: 'reference photo could not be fetched from storage — check server egress, then rescan',
    local_face_engine_unavailable: 'local face engine unavailable on the server — registry legs need the InsightFace model (ops: check startup logs)',
  }[reason] || (reason ? String(reason).replace(/_/g, ' ') : ''));
  const physicalData = physicalModule?.raw_output || {};
  const physicalChecks = physicalData.checks || {};
  // Iris verification: prefer top-level response field, fall back to persisted module
  const irisData = data.iris_verification || irisModule?.raw_output || null;
  const faceLive = livenessModule?.raw_output?.live;
  const biometricOverall = (() => {
    const faceOk = faceMatch.live_vs_doc_match === true;
    const faceBad = faceMatch.live_vs_doc_match === false;
    const irisOk = irisData?.match === true;
    const irisBad = irisData?.match === false;
    const liveBad = faceLive === false || irisData?.liveness_passed === false;
    if (faceBad || irisBad || liveBad) return 'FAIL';
    if (faceOk && (irisOk || !irisData?.captured)) return 'PASS';
    if (faceOk && irisOk) return 'PASS';
    return 'REVIEW';
  })();

  // A genuine registry comparison exists only when the backend actually
  // matched a citizen using trusted extraction (real Gemini or real local OCR)
  // — reported by the case API as db_record_found.
  const hasGenuineDbRecord = Boolean(data.db_record_found);

  // Structured verification summary (spec §10) — neutral shell, color only on badges
  const mismatchCount = (extracted_fields || []).filter((f) => f.match_status === 'mismatch').length;
  const summaryRows = [
    {
      label: 'DOCUMENT AUTHENTICITY',
      state: tamperModule?.status === 'inconclusive' ? 'REVIEW' : tamperModule?.score != null ? (tamperModule.score >= 0.5 ? 'FAIL' : tamperModule.score >= 0.25 ? 'REVIEW' : 'PASS') : 'NA',
      detail: tamperModule?.status === 'inconclusive' ? 'Tamper analysis inconclusive — physical inspection advised' : undefined,
    },
    {
      label: 'MRZ CONSISTENCY',
      state: checksumModule?.raw_output?.valid === true ? 'PASS' : checksumModule?.raw_output?.valid === false ? 'FAIL' : 'NA',
      detail: checksumModule?.raw_output?.algorithm ? `Algorithm: ${checksumModule.raw_output.algorithm}` : undefined,
    },
    {
      label: 'REGISTRY VERIFICATION',
      state: !hasGenuineDbRecord ? 'REVIEW' : mismatchCount > 0 ? 'REVIEW' : 'PASS',
      detail: !hasGenuineDbRecord ? 'No registry record available for comparison' : `${mismatchCount} field mismatch${mismatchCount === 1 ? '' : 'es'}`,
    },
    {
      label: 'FACE MATCH',
      state: faceMatch.live_vs_doc_match === true ? 'PASS' : faceMatch.live_vs_doc_match === false ? 'FAIL' : 'REVIEW',
      detail: faceMatch.similarity_score != null ? `Similarity ${(faceMatch.similarity_score * 100).toFixed(1)}%` : 'No biometric verdict produced',
    },
    {
      label: 'DEMOGRAPHICS',
      state: !hasGenuineDbRecord ? 'REVIEW' : mismatchCount === 0 ? 'PASS' : 'REVIEW',
      detail: `${extracted_fields.length} fields compared`,
    },
    {
      label: 'FRAUD INDICATORS',
      state: watchlistModule?.raw_output?.is_hit || deepfakeModule?.score >= 0.7 || faceLive === false ? 'FAIL' : livenessModule?.status === 'inconclusive' || deepfakeModule?.status === 'inconclusive' ? 'REVIEW' : 'NONE',
      detail: watchlistModule?.raw_output?.is_hit ? 'Watchlist hit requires supervisor review' : undefined,
    },
  ];
  const anomalyCount = summaryRows.filter((r) => r.state === 'FAIL' || r.state === 'REVIEW').length;

  return (
    <div className="animate-fade-in space-y-5 pb-8">
      <SEO
        title={caseLabel}
        description={`Forensic screening report for ${caseLabel}: demographic parity, 3-way face verification, tamper and deepfake analysis, liveness and watchlist results.`}
        path={`/case/${id}`}
        noindex
      />
      <Breadcrumbs items={[{ label: 'Overview', to: '/' }, { label: 'Case Queue', to: '/' }, { label: caseLabel }]} />
      <div className="flex items-start gap-3">
        <button onClick={() => navigate('/')} aria-label="Back to case dashboard" className="gov-icon-btn mt-1">
          <ArrowLeft size={20} aria-hidden="true" />
        </button>
        <div className="min-w-0">
          <h1 className="gov-page-title flex flex-wrap items-center gap-2">
            {caseLabel}
            <span className="gov-badge gov-badge-grey">
              <FileText size={13} aria-hidden="true" /> {c.document_type?.toUpperCase() || 'UNKNOWN'}
            </span>
            {(data.is_demo || geminiModule?.is_mocked || watchlistModule?.is_mocked) && (
              <MockedDataBadge />
            )}
          </h1>
          <p className="gov-subtitle">{new Date(c.timestamp).toLocaleString('en-IN')} · Version v{c.version ?? 0} · Status: {String(c.status || '').replace('_', ' ')}</p>
        </div>
      </div>

      <VerdictCard verdict={c.verdict} riskScore={c.risk_score} anomalyCount={anomalyCount} similarity={faceMatch.similarity_score} />

      {/* Verification summary — structured PASS/REVIEW/FAIL */}
      <section aria-label="Verification summary" className="gov-card-padded">
        <div className="mb-2 flex items-center justify-between gap-2 border-b border-[#D9DEE7] pb-3">
          <h2 className="gov-card-title">Verification Summary</h2>
          <span className="gov-badge gov-badge-grey">Verification Engine</span>
        </div>
        <div className="grid grid-cols-1 gap-x-8 md:grid-cols-2">
          {summaryRows.map((r) => (
            <CheckRow key={r.label} label={r.label} state={r.state} detail={r.detail} />
          ))}
        </div>
      </section>

      {/* Demo-only: simulated AI was excluded from scoring */}
      {(data.is_demo || geminiModule?.is_mocked) && (
        <GovNotice tone="amber" icon={<ShieldAlert size={18} className="mt-0.5 shrink-0" aria-hidden="true" />} title="DEMO ONLY — Simulated AI Excluded">
          {data.demo_label || geminiData.is_demo && 'This case used offline simulation for face/tamper AI. Those simulated results were excluded from the risk score — this verdict is DEMO ONLY and requires manual officer review.'}
          {!data.demo_label && !geminiData.is_demo && 'Gemini AI was offline, so face/tamper results are simulated and were excluded from scoring. Manual review required.'}
        </GovNotice>
      )}

      {/* Cloud unavailable — network failure fallback, local checks only */}
      {(data.cloud_unavailable || data.gemini_metadata?.cloud_unavailable || geminiData.cloud_unavailable) && (
        <GovNotice tone="amber" icon={<AlertTriangle size={18} className="mt-0.5 shrink-0" aria-hidden="true" />} title="CLOUD UNAVAILABLE — Local Checks Only">
          Cloud AI verification was unavailable due to network/cloud failure. Local forensic checks (tamper, liveness, OCR) completed, but final decision requires <strong>manual officer review</strong>. System did not halt — controlled fallback to Yellow applied.
          {geminiData.cloud_fallback_reason && ` Reason: ${geminiData.cloud_fallback_reason}.`}
        </GovNotice>
      )}

      {/* No DB record / unverifiable — alert the officer instead of faking a comparison */}
      {!hasGenuineDbRecord && (
        <GovNotice tone="amber" icon={<AlertTriangle size={18} className="mt-0.5 shrink-0" aria-hidden="true" />} title="NO DOCUMENT FOUND IN THE DATABASE">
          No matching record exists in the citizens registry for this document, or the
          document could not be read automatically. The identity could not be verified
          against the database — manual verification by the officer/supervisor is required.
        </GovNotice>
      )}

      {/* Recapture requested — face image quality too poor for a biometric verdict */}
      {(faceMatch.recapture_requested || faceMatch.face_quality?.gate === 'failed') && (
        <GovNotice tone="blue" icon={<ScanLine size={18} className="mt-0.5 shrink-0" aria-hidden="true" />} title={`RECAPTURE NEEDED${(faceMatch.recapture_target && faceMatch.recapture_target !== 'both') ? ` — ${String(faceMatch.recapture_target).toUpperCase()}` : ''}`}>
          No biometric verdict was produced — the {(faceMatch.recapture_target === 'document' ? 'document photo' : faceMatch.recapture_target === 'live' ? 'live capture' : 'face images')} failed quality checks. This is a capture problem, not an identity mismatch.
          {(faceMatch.recapture_reasons?.length > 0) && (
            <ul className="mt-2 list-disc space-y-1 pl-5">
              {faceMatch.recapture_reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          )}
        </GovNotice>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">

        {/* Left column — Demographic Parity + Biometric Verification + Tamper Detection */}
        <div className="min-w-0 space-y-5">
        <div className="gov-card-padded">
          <div className="mb-3 flex flex-wrap items-center gap-2 border-b border-[#D9DEE7] pb-3">
            <UserRound className="text-[#123B66]" size={18} aria-hidden="true" />
            <h2 className="gov-card-title">Demographic Parity</h2>
            {!hasGenuineDbRecord && (
              <StatusBadge tone="amber" icon={<AlertTriangle size={12} aria-hidden="true" />}>NO DB RECORD</StatusBadge>
            )}
          </div>

          {!hasGenuineDbRecord && (
            <div className="gov-notice gov-notice-amber mb-3">
              No database record is available to compare against. The officer must
              verify this identity manually against the document.
            </div>
          )}

          {/* Compact wrapping field list — no min-width, no side-scroll.
              Long values wrap onto multiple lines instead of scrolling. */}
          <div className="divide-y divide-[#EAEDEF]">
            {extracted_fields.map(f => (
              <div key={f.id} className="flex items-start justify-between gap-3 py-2.5 first:pt-0 last:pb-0">
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] font-semibold break-words text-[#172033]">{f.field_name}</p>
                  <p className="mt-1 text-xs break-words text-[#667085]">
                    <span className="font-semibold text-[#98A2B3]">Doc: </span>
                    <span className="font-mono">{maskAadhaar(f.field_name, f.extracted_value) || '–'}</span>
                  </p>
                  <p className="mt-0.5 text-xs break-words text-[#667085]">
                    <span className="font-semibold text-[#98A2B3]">DB: </span>
                    <span className="font-mono">{maskAadhaar(f.field_name, f.database_value) || '–'}</span>
                  </p>
                </div>
                <span className="shrink-0">
                  {f.match_status === 'match' ? (
                    <span className="gov-badge gov-badge-green"><Check size={13} aria-hidden="true" /> Match</span>
                  ) : f.match_status === 'mismatch' ? (
                    <span className="gov-badge gov-badge-red"><X size={13} aria-hidden="true" /> Mismatch</span>
                  ) : (
                    <span className="gov-badge gov-badge-grey">N/A</span>
                  )}
                </span>
              </div>
            ))}
            {extracted_fields.length === 0 && (
              <p className="py-6 text-center text-sm text-[#667085]">No demographic data extracted.</p>
            )}
          </div>
        </div>

        {/* Biometric Verification — one person capture: face + iris + liveness */}
        <div className="gov-card-padded">
          <div className="mb-3 flex flex-wrap items-center gap-2 border-b border-[#D9DEE7] pb-3">
            <Eye className="text-[#1769AA]" size={18} aria-hidden="true" />
            <h2 className="gov-card-title">Biometric Verification</h2>
            <span className={`gov-badge ml-auto ${biometricOverall === 'PASS' ? 'gov-badge-green' : biometricOverall === 'FAIL' ? 'gov-badge-red' : 'gov-badge-amber'}`}>
              {biometricOverall}
            </span>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="min-w-0 rounded-lg border border-[#D9DEE7] bg-[#F7F8FA] p-3">
              <h3 className="mb-2 text-xs font-bold uppercase tracking-[0.06em] text-[#667085]">Face</h3>
              <div className="space-y-1 text-xs">
                <div className="flex justify-between gap-2"><span className="shrink-0 text-[#667085]">Captured</span><span className="text-right font-medium break-words text-[#172033]">{faceMatch.similarity_score != null || faceMatch.live_vs_doc_match != null ? 'Yes' : 'No'}</span></div>
                <div className="flex justify-between gap-2"><span className="shrink-0 text-[#667085]">Match</span><span className={faceMatch.live_vs_doc_match === true ? 'font-semibold text-[#16803C]' : faceMatch.live_vs_doc_match === false ? 'font-semibold text-[#C62828]' : 'text-[#98A2B3]'}>{faceMatch.live_vs_doc_match === true ? 'Match' : faceMatch.live_vs_doc_match === false ? 'Mismatch' : 'N/A'}</span></div>
                <div className="flex justify-between gap-2"><span className="shrink-0 text-[#667085]">Similarity</span><span className="font-mono text-[#172033]">{faceMatch.similarity_score != null ? `${(faceMatch.similarity_score * 100).toFixed(1)}%` : 'N/A'}</span></div>
                <div className="flex justify-between gap-2"><span className="shrink-0 text-[#667085]">Quality</span><span className="text-right break-words text-[#172033]">{faceMatch.face_quality?.gate || 'N/A'}</span></div>
                <div className="flex justify-between gap-2"><span className="shrink-0 text-[#667085]">Liveness</span><span className={faceLive === true ? 'font-semibold text-[#16803C]' : faceLive === false ? 'font-semibold text-[#C62828]' : 'text-[#98A2B3]'}>{faceLive === true ? 'Passed' : faceLive === false ? 'Failed' : 'N/A'}</span></div>
              </div>
            </div>
            <div className="min-w-0 rounded-lg border border-[#D9DEE7] bg-[#F7F8FA] p-3">
              <h3 className="mb-2 text-xs font-bold uppercase tracking-[0.06em] text-[#667085]">Iris</h3>
              {!irisData?.captured ? (
                <p className="text-xs break-words text-[#667085]">Not captured — single person capture includes iris when eyes are visible.</p>
              ) : (
                <div className="space-y-1 text-xs">
                  <div className="flex justify-between gap-2"><span className="shrink-0 text-[#667085]">Captured</span><span className="text-right break-words text-[#172033]">Yes{irisData.source === 'unified_burst_derived' ? ' (same capture)' : ''}</span></div>
                  <div className="flex justify-between gap-2"><span className="shrink-0 text-[#667085]">Eye</span><span className="text-[#172033]">{irisData.eye || 'N/A'}</span></div>
                  <div className="flex justify-between gap-2"><span className="shrink-0 text-[#667085]">Match</span><span className={irisData.match === true ? 'font-semibold text-[#16803C]' : irisData.match === false ? 'font-semibold text-[#C62828]' : 'text-[#98A2B3]'}>{irisData.match === true ? 'Match' : irisData.match === false ? 'Mismatch' : 'N/A'}</span></div>
                  <div className="flex justify-between gap-2"><span className="shrink-0 text-[#667085]">Distance</span><span className="font-mono text-[#172033]">{irisData.distance != null ? Number(irisData.distance).toFixed(3) : 'N/A'}</span></div>
                  <div className="flex justify-between gap-2"><span className="shrink-0 text-[#667085]">Quality</span><span className="text-right break-words text-[#172033]">{irisData.quality != null ? Number(irisData.quality).toFixed(2) : 'N/A'}{irisData.quality_usable === false ? ' (low)' : ''}</span></div>
                  <div className="flex justify-between gap-2"><span className="shrink-0 text-[#667085]">PAD</span><span className={irisData.liveness_passed === true ? 'font-semibold text-[#16803C]' : irisData.liveness_passed === false ? 'font-semibold text-[#C62828]' : 'text-[#98A2B3]'}>{irisData.liveness_passed === true ? 'Passed' : irisData.liveness_passed === false ? 'Failed' : 'N/A'}</span></div>
                  {irisData.reason && <p className="pt-1 text-[11px] break-words text-[#667085]">{irisData.reason}</p>}
                </div>
              )}
              <p className="mt-2 text-[11px] text-[#98A2B3]">Iris is RGB-prototype (not NIR).</p>
            </div>
            <div className="min-w-0 rounded-lg border border-[#D9DEE7] bg-[#F7F8FA] p-3">
              <h3 className="mb-2 text-xs font-bold uppercase tracking-[0.06em] text-[#667085]">Liveness</h3>
              <div className="space-y-1 text-xs">
                <div className="flex justify-between gap-2"><span className="shrink-0 text-[#667085]">Status</span><span className="text-right break-words text-[#172033]">{livenessModule?.status || 'N/A'}</span></div>
                <div className="flex justify-between gap-2"><span className="shrink-0 text-[#667085]">Score</span><span className="font-mono text-[#172033]">{livenessModule?.score != null ? Number(livenessModule.score).toFixed(2) : 'N/A'}</span></div>
                <div className="flex justify-between gap-2"><span className="shrink-0 text-[#667085]">Challenge</span><span className="text-right break-words text-[#172033]">{c.challenge_type || livenessModule?.raw_output?.challenge_type || 'N/A'}</span></div>
              </div>
            </div>
          </div>
        </div>

        {/* Tamper Detection */}
        <div className="gov-card-padded">
          <div className="mb-3 flex flex-col gap-2 border-b border-[#D9DEE7] pb-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2">
              <Activity className="text-[#B7791F]" size={18} aria-hidden="true" />
              <h2 className="gov-card-title">Tamper Detection</h2>
            </div>
            {tamperModule && <StatusBadgeLocal status={tamperModule.status} score={tamperModule.score} />}
          </div>
          {tamperModule?.evidence_uri ? (
            <div className="overflow-hidden rounded-lg border border-[#D9DEE7]">
              <EvidenceImage
                evidenceUri={tamperModule.evidence_uri}
                alt="Error Level Analysis heatmap overlay highlighting suspected tampered regions of the submitted identity document"
              />
              <p className="border-t border-[#D9DEE7] bg-[#F7F8FA] px-3 py-1.5 text-xs font-medium text-[#667085]">ELA Heatmap Overlay</p>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[#D9DEE7] bg-[#F7F8FA] p-8 text-[#98A2B3]">
              <ImageIcon size={30} className="mb-2 opacity-60" aria-hidden="true" />
              <p className="text-center text-sm">{tamperModule?.status === 'inconclusive' ? 'Tamper analysis was inconclusive.' : 'No visual evidence generated.'}</p>
            </div>
          )}
        </div>
        </div>

        {/* Right column — 3-Way Face Match + Physical Forgery */}
        <div className="min-w-0 space-y-5">
          <div className="gov-card-padded">
            <div className="mb-3 flex flex-wrap items-center gap-2 border-b border-[#D9DEE7] pb-3">
              <ScanLine className="text-[#1769AA]" size={18} aria-hidden="true" />
              <h2 className="gov-card-title">3-Way Face Match</h2>
              {geminiModule && !geminiModule.is_mocked && <StatusBadgeLocal status={geminiModule.status} />}
              {geminiModule?.is_mocked && hasRealFaceVerdict && (
                <StatusBadge tone="green">Local biometric</StatusBadge>
              )}
            </div>

            {!hasRealFaceVerdict ? (
              <div className="gov-notice gov-notice-amber">
                <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
                {geminiModule?.is_mocked
                  ? 'AI face verification is unavailable in this environment. No simulated results are displayed during document verification.'
                  : 'AI module was inconclusive. Face verification results are not available.'}
              </div>
            ) : (
              <>
                {geminiModule?.is_mocked && (
                  <div className="gov-notice gov-notice-blue mb-3">
                    Cloud AI was offline — the pairs below are the evidence-backed local biometric verification (InsightFace), not cloud results.
                  </div>
                )}
                <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className="flex items-center justify-between rounded-lg border border-[#D9DEE7] bg-[#F7F8FA] p-3">
                    <span className="text-sm text-[#667085]">Live vs Doc</span>
                    {faceMatch.live_vs_doc_match === true ? <span className="gov-badge gov-badge-green"><Check size={13} aria-hidden="true" /> Match</span> :
                     faceMatch.live_vs_doc_match === false ? <span className="gov-badge gov-badge-red"><X size={13} aria-hidden="true" /> Mismatch</span> :
                     <span className="gov-badge gov-badge-grey">N/A</span>}
                  </div>
                  <div className="flex items-center justify-between rounded-lg border border-[#D9DEE7] bg-[#F7F8FA] p-3">
                    <span className="text-sm text-[#667085]">Doc vs DB</span>
                    {faceMatch.doc_vs_db_match === true ? <span className="gov-badge gov-badge-green"><Check size={13} aria-hidden="true" /> Match</span> :
                     faceMatch.doc_vs_db_match === false ? <span className="gov-badge gov-badge-red"><X size={13} aria-hidden="true" /> Mismatch</span> :
                     <span className="gov-badge gov-badge-grey">N/A</span>}
                  </div>
                  <div className="flex items-center justify-between rounded-lg border border-[#D9DEE7] bg-[#F7F8FA] p-3">
                    <span className="text-sm text-[#667085]">Live vs DB</span>
                    {faceMatch.live_vs_db_match === true ? <span className="gov-badge gov-badge-green"><Check size={13} aria-hidden="true" /> Match</span> :
                     faceMatch.live_vs_db_match === false ? <span className="gov-badge gov-badge-red"><X size={13} aria-hidden="true" /> Mismatch</span> :
                     <span className="gov-badge gov-badge-grey">N/A</span>}
                  </div>
                  <div className="flex flex-col justify-center rounded-lg border border-[#D9DEE7] bg-[#F7F8FA] p-3 text-center">
                    <span className="text-xs font-semibold uppercase tracking-wide text-[#667085]">Similarity Score</span>
                    <span className="text-2xl font-bold text-[#172033]">{faceMatch.similarity_score != null ? `${(faceMatch.similarity_score * 100).toFixed(1)}%` : 'N/A'}</span>
                  </div>
                </div>

                {faceMatch.visual_reasoning && (
                  <div className="rounded-lg border border-[#1769AA]/25 bg-[#EAF2FA] p-3">
                    <h3 className="mb-1 text-xs font-bold uppercase tracking-[0.06em] text-[#123B66]">Forensic Reasoning</h3>
                    <p className="text-sm leading-relaxed text-[#172033]">{faceMatch.visual_reasoning}</p>
                  </div>
                )}

                {/* Three-way completeness — every advertised pair traced to evidence */}
                {(faceMatch.comparison_completeness || faceMatch.pair_sources) && (
                  <div className="mt-3 rounded-lg border border-[#D9DEE7] bg-[#F7F8FA] p-3 text-xs text-[#667085]">
                    <span className="font-semibold uppercase tracking-wide text-[#172033]">Registry comparison: </span>
                    {faceMatch.comparison_completeness === 'complete' ? (
                      <span className="font-medium text-[#16803C]">complete — doc↔live, doc↔registry and live↔registry all measured</span>
                    ) : faceMatch.comparison_completeness === 'partial' ? (
                      <span className="font-medium text-[#B7791F]">partial{faceMatch.db_pairs_unavailable_reason ? ` — registry legs unavailable: ${dbPairsReasonText(faceMatch.db_pairs_unavailable_reason)}` : ''}{faceMatch.db_photo_late ? ' (registry record identified after the AI scan; registry legs measured locally)' : ''}</span>
                    ) : (
                      <span>unavailable</span>
                    )}
                    {faceMatch.pair_sources && (
                      <div className="mt-1 font-mono text-[11px]">
                        live↔doc: {faceMatch.pair_sources.live_vs_doc || 'n/a'} · doc↔db: {faceMatch.pair_sources.doc_vs_db || 'n/a'} · live↔db: {faceMatch.pair_sources.live_vs_db || 'n/a'}
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>

          {/* Physical Forgery — layout/font/photo-frame/print-scan/QR/security print */}
          <div className="gov-card-padded">
            <div className="mb-3 flex flex-col gap-2 border-b border-[#D9DEE7] pb-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2">
                <Fingerprint className="text-[#1769AA]" size={18} aria-hidden="true" />
                <h2 className="gov-card-title">Physical Forgery</h2>
              </div>
              {physicalModule && <StatusBadgeLocal status={physicalModule.status} score={physicalModule.score} />}
            </div>
            {!physicalModule ? (
              <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[#D9DEE7] bg-[#F7F8FA] p-8 text-[#98A2B3]">
                <ImageIcon size={30} className="mb-2 opacity-60" aria-hidden="true" />
                <p className="text-sm">Physical-forgery analysis not available for this case (screened before this check shipped).</p>
              </div>
            ) : physicalModule.status === 'inconclusive' ? (
              <div className="gov-notice gov-notice-amber">
                <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
                Physical-forgery analysis was inconclusive. Inspect the document physically.
              </div>
            ) : (
              <div className="space-y-2">
                {Object.entries(physicalChecks).map(([name, chk]) => (
                  <div key={name} className="rounded-lg border border-[#D9DEE7] bg-[#F7F8FA] p-3">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-sm font-medium text-[#172033]">{name.replace(/_/g, ' ')}</span>
                      <span className={`font-mono text-xs font-semibold ${chk.status !== 'ok' ? 'text-[#98A2B3]' : chk.score >= 0.5 ? 'text-[#C62828]' : chk.score >= 0.25 ? 'text-[#B7791F]' : 'text-[#16803C]'}`}>
                        {chk.status !== 'ok' ? chk.status.replace(/_/g, ' ') : `${(chk.score * 100).toFixed(0)}%`}
                      </span>
                    </div>
                    <div className="mt-2 h-1.5 rounded-full bg-[#E4E9F1]">
                      <div className={`h-1.5 rounded-full ${chk.status !== 'ok' ? 'bg-[#BEC6D5]' : chk.score >= 0.5 ? 'bg-[#C62828]' : chk.score >= 0.25 ? 'bg-[#B7791F]' : 'bg-[#16803C]'}`} style={{ width: `${chk.status === 'ok' ? Math.round(chk.score * 100) : 0}%` }} />
                    </div>
                    {(chk.details?.findings?.length > 0) && (
                      <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-[#667085]">
                        {chk.details.findings.map((f, i) => <li key={i}>{f}</li>)}
                      </ul>
                    )}
                  </div>
                ))}
                {(physicalData.checks_fired?.length > 0) && (
                  <p className="text-xs text-[#98A2B3]">Fired: {physicalData.checks_fired.join(', ').replace(/_/g, ' ')}</p>
                )}
                {(() => {
                  const qr = physicalChecks.qr_barcode;
                  const codes = qr?.details?.codes || [];
                  if (!qr || qr.status !== 'ok' || codes.length === 0) return null;
                  return (
                    <div className="rounded-lg border border-[#1769AA]/25 bg-[#EAF2FA] p-3">
                      <p className="text-sm font-semibold text-[#123B66]">
                        QR / Barcode — {qr.details.codes_found} decoded ({(qr.details.formats || []).join(', ')})
                      </p>
                      <div className="mt-2 space-y-2">
                        {codes.map((cd, i) => (
                          <div key={i} className="rounded border border-[#D9DEE7] bg-white p-2">
                            <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
                              <span className="text-xs text-[#667085]">{cd.format}</span>
                              <span className={`text-[11px] font-semibold ${cd.cross_check === 'consistent_with_document_number' ? 'text-[#16803C]' : cd.cross_check === 'payload_differs_from_document_number' ? 'text-[#C62828]' : 'text-[#98A2B3]'}`}>
                                {cd.cross_check === 'consistent_with_document_number' ? '✓ matches document number'
                                  : cd.cross_check === 'payload_differs_from_document_number' ? '✕ differs from document number — possible swapped code'
                                  : 'no document link asserted'}
                              </span>
                            </div>
                            <p className="mt-1 break-all font-mono text-[11px] text-[#172033]">{cd.payload}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })()}
              </div>
            )}
            {physicalModule?.evidence_uri && (
              <div className="mt-3 overflow-hidden rounded-lg border border-[#D9DEE7]">
                <EvidenceImage
                  evidenceUri={physicalModule.evidence_uri}
                  alt="Physical-forgery zone overlay marking the MRZ band and portrait frame examined for layout, font and frame anomalies"
                />
                <p className="border-t border-[#D9DEE7] bg-[#F7F8FA] px-3 py-1.5 text-xs font-medium text-[#667085]">Forgery Zone Overlay</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Analysis Details (expandable) — Deepfake, Liveness, Checksum, Security Zones */}
      <section aria-label="Analysis details" className="space-y-3">
        <h2 className="gov-section-title">Analysis Details</h2>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Details title="Deepfake Detection">
            {deepfakeModule ? (
              <div className="space-y-2 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[#667085]">Status</span>
                  <StatusBadgeLocal status={deepfakeModule.status} score={deepfakeModule.score} />
                </div>
                {deepfakeModule.raw_output?.method && (
                  <p className="text-xs text-[#667085]">Method: {deepfakeModule.raw_output.method}</p>
                )}
                {deepfakeModule.raw_output?.metrics && (
                  <div className="space-y-1 rounded-lg bg-[#F7F8FA] p-3 text-xs">
                    <div className="flex justify-between gap-3"><span className="text-[#667085]">HF Fraction</span><span className="font-mono text-[#172033]">{deepfakeModule.raw_output.metrics.high_frequency_fraction?.toFixed(4)}</span></div>
                    <div className="flex justify-between gap-3"><span className="text-[#667085]">Spectral Peakedness</span><span className="font-mono text-[#172033]">{deepfakeModule.raw_output.metrics.spectral_peakedness?.toFixed(4)}</span></div>
                    <div className="flex justify-between gap-3"><span className="text-[#667085]">Rolloff Ratio</span><span className="font-mono text-[#172033]">{deepfakeModule.raw_output.metrics.rolloff_ratio?.toFixed(4)}</span></div>
                  </div>
                )}
              </div>
            ) : <p className="text-sm text-[#667085]">No deepfake analysis available.</p>}
          </Details>
          <Details title="Liveness Detection">
            {livenessModule ? (
              <div className="space-y-2 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[#667085]">Status</span>
                  <StatusBadgeLocal status={livenessModule.status} score={livenessModule.score} />
                </div>
                {livenessModule.raw_output?.live !== undefined && (
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-[#667085]">Result</span>
                    {livenessModule.raw_output.live ? (
                      <span className="gov-badge gov-badge-green"><Radio size={13} aria-hidden="true" /> Live</span>
                    ) : (
                      <span className="gov-badge gov-badge-red"><X size={13} aria-hidden="true" /> Spoof Suspected</span>
                    )}
                  </div>
                )}
                {livenessModule.raw_output?.blink_count !== undefined && (
                  <div className="space-y-1 rounded-lg bg-[#F7F8FA] p-3 text-xs">
                    <div className="flex justify-between gap-3"><span className="text-[#667085]">Blink Count</span><span className="font-mono text-[#172033]">{livenessModule.raw_output.blink_count}</span></div>
                    <div className="flex justify-between gap-3"><span className="text-[#667085]">Frames Analysed</span><span className="font-mono text-[#172033]">{livenessModule.raw_output.frames_analysed}</span></div>
                    {livenessModule.raw_output?.ear_stats && (
                      <div className="flex justify-between gap-3"><span className="text-[#667085]">EAR Swing</span><span className="font-mono text-[#172033]">{livenessModule.raw_output.ear_stats.swing?.toFixed(4)}</span></div>
                    )}
                  </div>
                )}
                {livenessModule.status === 'inconclusive' && (
                  <div className="gov-notice gov-notice-amber !p-2.5 !text-xs">
                    {livenessModule.raw_output?.reason || 'Liveness check was inconclusive. A multi-frame burst is required for reliable detection.'}
                  </div>
                )}
              </div>
            ) : <p className="text-sm text-[#667085]">No liveness data available.</p>}
          </Details>
          <Details title="Checksum Validation">
            {checksumModule ? (
              <div className="space-y-2 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[#667085]">Document Type</span>
                  <span className="font-medium text-[#172033]">{checksumModule.raw_output?.document_type?.toUpperCase() || '-'}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[#667085]">Valid</span>
                  {checksumModule.raw_output?.valid === true ? (
                    <span className="gov-badge gov-badge-green"><Check size={13} aria-hidden="true" /> Pass</span>
                  ) : checksumModule.raw_output?.valid === false ? (
                    <span className="gov-badge gov-badge-red"><X size={13} aria-hidden="true" /> Fail</span>
                  ) : (
                    <span className="gov-badge gov-badge-grey">N/A — not digitally verifiable</span>
                  )}
                </div>
                {checksumModule.raw_output?.algorithm && (
                  <p className="text-xs text-[#667085]">Algorithm: {checksumModule.raw_output.algorithm}</p>
                )}
              </div>
            ) : <p className="text-sm text-[#667085]">No checksum data available.</p>}
          </Details>
        </div>
        <Details title="Security Zones — legacy zone analysis">
          {(() => {
            const sz = module_results.find(m => m.module_name === 'security_zones');
            if (!sz) return <p className="text-sm text-[#667085]">No security zone analysis available.</p>;
            return (
              <div className="space-y-2 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[#667085]">Status</span>
                  <StatusBadgeLocal status={sz.status} score={sz.score} />
                </div>
                {sz.raw_output?.checks && (
                  <div className="space-y-1 rounded-lg bg-[#F7F8FA] p-3 text-xs">
                    {Object.entries(sz.raw_output.checks).map(([k, v]) => (
                      <div key={k} className="flex justify-between gap-3">
                        <span className="text-[#667085]">{k.replace(/_/g, ' ')}</span>
                        <span className="font-mono text-[11px] text-[#172033]">{String(v).slice(0, 40)}</span>
                      </div>
                    ))}
                  </div>
                )}
                {sz.evidence_uri && <p className="text-xs text-[#667085]">Zone overlay: {sz.evidence_uri.split('/').pop()}</p>}
              </div>
            );
          })()}
        </Details>
      </section>

      {/* Watchlist Panel — always shown, even on clear (audit P2 §6) */}
      <section aria-label="Watchlist lookup" className={`gov-card-padded ${!watchlistModule?.is_mocked && watchlistModule?.raw_output?.is_hit ? 'border-l-4 !border-l-[#C62828]' : ''}`}>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <ShieldAlert className={!watchlistModule?.is_mocked && watchlistModule?.raw_output?.is_hit ? 'text-[#C62828]' : 'text-[#667085]'} size={20} aria-hidden="true" />
          <h2 className="gov-card-title">Watchlist Lookup</h2>
          {watchlistModule?.is_mocked && <MockedDataBadge />}
          {!watchlistModule?.is_mocked && (watchlistModule?.raw_output?.is_hit ? (
            <span className="gov-badge gov-badge-red">HIT</span>
          ) : (
            <span className="gov-badge gov-badge-green"><Check size={13} aria-hidden="true" /> CLEAR</span>
          ))}
        </div>
        {watchlistModule?.is_mocked ? (
          <p className="text-sm text-[#667085]">
            Watchlist registry is not connected. Lookout results are unavailable and were not used in this screening.
          </p>
        ) : watchlistModule?.raw_output?.is_hit ? (
          <div className="space-y-2">
            {watchlistModule.raw_output.hits.map((hit, i) => (
              <div key={i} className="rounded-lg border border-[#C62828]/30 bg-[#FBEAEA] p-3">
                <p className="text-sm font-semibold text-[#172033]">{hit.name} <span className="ml-0 block font-normal text-[#667085] sm:ml-2 sm:inline">ID: {hit.id_number}</span></p>
                <p className="mt-1 text-sm font-medium text-[#C62828]">{hit.source}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-[#667085]">No watchlist matches found for this traveler.</p>
        )}
      </section>

      {/* Officer Action — state machine: pending_review -> escalated -> decided; deny requires supervisor */}
      {(() => {
        const myRole = (localStorage.getItem('role') || 'officer').toLowerCase();
        const isAuditor = myRole === 'auditor';
        const isOfficer = myRole === 'officer';
        if (c.status === 'decided') {
          return (
            <div className="gov-card-padded mt-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3 text-[#172033]">
                <ShieldCheck size={20} className="text-[#667085]" aria-hidden="true" />
                <span className="font-semibold">Case Adjudicated</span>
              </div>
              <span className="gov-badge gov-badge-grey w-fit uppercase">Status: decided (v{c.version ?? 0})</span>
            </div>
          );
        }
        if (c.status === 'escalated') {
          return (
            <div className="gov-card-padded mt-6 border-t-4 !border-t-[#B7791F]">
              <div className="mb-3 flex items-center gap-2 text-[#B7791F]">
                <AlertTriangle size={18} aria-hidden="true" />
                <h2 className="gov-card-title !text-[#7A5410]">Escalated — Awaiting Supervisor Decision</h2>
              </div>
              <p className="mb-4 text-sm text-[#667085]">This case was escalated for supervisor review. Only a supervisor can clear or deny it.</p>
              {isAuditor ? (
                <p className="text-sm text-[#667085]">Auditor role is read-only.</p>
              ) : isOfficer ? (
                <p className="text-sm text-[#667085]">Your role cannot decide escalated cases.</p>
              ) : (
                <div className="space-y-4">
                  <label htmlFor="adjudication-reason" className="gov-label">
                    Decision justification <span className="font-normal text-[#667085]">(required, minimum 3 characters)</span>
                  </label>
                  <textarea id="adjudication-reason" value={reason} onChange={(e) => setReason(e.target.value)} className="gov-textarea" placeholder="Record the grounds for this decision…" />
                  {actionError && (<div role="alert" className="gov-notice gov-notice-red">{actionError}</div>)}
                  <div className="flex flex-col gap-3 sm:flex-row sm:gap-3">
                    <button onClick={() => handleAction('clear')} disabled={actionLoading} className="gov-btn gov-btn-primary flex-1"><CheckCircle2 size={17} aria-hidden="true" /> Clear Traveler</button>
                    <button onClick={() => handleAction('deny')} disabled={actionLoading} className="gov-btn gov-btn-danger flex-1"><X size={17} aria-hidden="true" /> Deny Entry</button>
                  </div>
                </div>
              )}
            </div>
          );
        }
        // pending_review
        return (
          <div className="gov-card-padded mt-6 border-t-4 !border-t-[#123B66]">
            <h2 className="gov-card-title mb-3">Officer Adjudication <span className="text-xs font-normal text-[#98A2B3]">(v{c.version ?? 0})</span></h2>
            <div className="space-y-4">
              <label htmlFor="adjudication-reason" className="gov-label">
                Decision justification <span className="font-normal text-[#667085]">(required, minimum 3 characters)</span>
              </label>
              <textarea id="adjudication-reason" value={reason} onChange={(e) => setReason(e.target.value)} className="gov-textarea" placeholder="Record the grounds for this decision…" />
              {actionError && (<div role="alert" className="gov-notice gov-notice-red">{actionError}</div>)}
              <div className="flex flex-col gap-3 sm:flex-row sm:gap-3">
                <button onClick={() => handleAction('clear')} disabled={actionLoading} className="gov-btn gov-btn-primary flex-1"><CheckCircle2 size={17} aria-hidden="true" /> Clear Traveler</button>
                {isOfficer ? (
                  <button disabled className="gov-btn flex-1 cursor-not-allowed border border-[#D9DEE7] bg-[#F1F4F9] text-[#98A2B3]" title="Deny requires supervisor approval — use Escalate"><X size={17} aria-hidden="true" /> Deny (Supervisor Only)</button>
                ) : (
                  <button onClick={() => handleAction('deny')} disabled={actionLoading || isAuditor} className="gov-btn gov-btn-danger flex-1 disabled:opacity-50"><X size={17} aria-hidden="true" /> Deny Entry</button>
                )}
                <button onClick={() => handleAction('escalate')} disabled={actionLoading || isAuditor} className="gov-btn gov-btn-secondary flex-1 !border-[#B7791F] !text-[#7A5410] hover:!bg-[#FBF3E2] disabled:opacity-50"><ShieldCheck size={17} aria-hidden="true" /> Escalate to Supervisor</button>
              </div>
              {isAuditor && <p className="text-xs text-[#667085]">Auditor is read-only.</p>}
            </div>
          </div>
        );
      })()}

      {/* Verification Evidence / Audit Details — provenance */}
      <section aria-label="Verification evidence and audit details" className="space-y-3">
        <h2 className="gov-section-title">Verification Evidence &amp; Audit Details</h2>
        <Details title="Decision provenance — signed record for reproducibility">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Hash size={16} className="text-[#667085]" aria-hidden="true" />
            {provVerified === true && <span className="gov-badge gov-badge-green">✓ Signed &amp; Verified</span>}
            {provVerified === false && <span className="gov-badge gov-badge-red">✕ Signature Mismatch</span>}
            {provenance && !provVerified && provenance.provenance && <span className="gov-badge gov-badge-amber">Unverified</span>}
          </div>
          {!provenance || !provenance.provenance ? (
            <p className="text-sm text-[#667085]">No provenance recorded for this case (created before provenance tracking).</p>
          ) : (
            <div className="space-y-3 font-mono text-xs">
              <div className="grid grid-cols-2 gap-3 text-[#172033]">
                <div><span className="text-[#667085]">Code:</span> {provenance.provenance.code_version?.slice(0, 12) || '—'}</div>
                <div><span className="text-[#667085]">At:</span> {provenance.provenance.timestamp ? new Date(provenance.provenance.timestamp).toLocaleString('en-IN') : '—'}</div>
                <div><span className="text-[#667085]">Face thr:</span> {provenance.provenance.thresholds?.face_match}</div>
                <div><span className="text-[#667085]">Tamper hi:</span> {provenance.provenance.thresholds?.tamper_high}</div>
                <div className="col-span-2"><span className="text-[#667085]">Input hashes:</span> {Object.entries(provenance.provenance.input_hashes || {}).map(([k, v]) => `${k}:${String(v).slice(0, 8)}`).join(' ') || '—'}</div>
                <div className="col-span-2"><span className="text-[#667085]">Models:</span> {Object.entries(provenance.provenance.models || {}).map(([k, v]) => `${k}:${v.threshold || v.model || ''}`).join(' | ').slice(0, 120) || '—'}</div>
              </div>
              <Details title="Full provenance JSON">
                <pre className="max-h-64 overflow-auto text-[11px] leading-snug whitespace-pre-wrap text-[#172033] break-all">{JSON.stringify(provenance.provenance, null, 2)}</pre>
                <p className="mt-2 text-[11px] text-[#667085]">Signature: {provenance.provenance_signature?.slice(0, 32) || '—'}…</p>
              </Details>
            </div>
          )}
        </Details>
      </section>
    </div>
  );
}
