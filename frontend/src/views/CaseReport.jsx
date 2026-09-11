import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ShieldAlert, CheckCircle, AlertTriangle, ArrowLeft, Loader2, User,
  FileText, Image as ImageIcon, Check, X, Shield, Activity, Scan,
  Eye, Fingerprint, Hash, Radio
} from 'lucide-react';
import api from '../api';
import SEO from '../components/SEO';
import Breadcrumbs from '../components/Breadcrumbs';

const VerdictBanner = ({ verdict }) => {
  const styles = {
    Green: 'bg-success/20 text-success border-success/50',
    Yellow: 'bg-warning/20 text-warning border-warning/50',
    Red: 'bg-danger/20 text-danger border-danger/50',
  };
  const icons = {
    Green: <CheckCircle size={28} className="text-success" />,
    Yellow: <AlertTriangle size={28} className="text-warning" />,
    Red: <ShieldAlert size={28} className="text-danger" />
  };
  // Audit P2 §7: no detention/denial language in automated output
  const descriptions = {
    Green: 'All checks passed. Low risk. Recommend clearance pending officer confirmation.',
    Yellow: 'Anomalies detected. Manual review required by reviewing officer.',
    Red: 'Critical risk flags detected. Escalation recommended for officer review.',
  };
  return (
    <div className={`flex flex-col gap-4 rounded-xl border p-4 sm:flex-row sm:items-center sm:p-6 ${styles[verdict] || 'bg-slate-800 text-slate-300 border-slate-700'} glass-panel`}>
      <div className="p-3 bg-black/20 rounded-full">
        {icons[verdict]}
      </div>
      <div>
        <h2 className="text-lg font-bold">SYSTEM VERDICT: {(verdict || 'UNKNOWN').toUpperCase()}</h2>
        <p className="text-sm opacity-90 mt-1">{descriptions[verdict] || 'Unable to determine risk level.'}</p>
      </div>
    </div>
  );
};

/** Module status indicator */
const StatusBadge = ({ status, score }) => {
  if (status === 'inconclusive') {
    return <span className="text-xs px-2 py-0.5 bg-warning/10 text-warning rounded border border-warning/30">Inconclusive</span>;
  }
  if (score !== null && score !== undefined) {
    const color = score > 0.5 ? 'text-danger' : 'text-success';
    return (
      <span className="text-sm px-2 py-1 bg-black/40 rounded border border-slate-700 text-slate-300">
        Score: <span className={color}>{(score * 100).toFixed(0)}%</span>
      </span>
    );
  }
  return <span className="text-xs px-2 py-0.5 bg-success/10 text-success rounded border border-success/30">OK</span>;
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
          setSrc(`/api/evidence/view?token=${encodeURIComponent(res.data.token)}`);
        }
      } catch {
        if (!cancelled) setError(true);
      }
    };
    fetchToken();
    return () => { cancelled = true; };
  }, [evidenceUri]);
  if (error) return <p className="text-sm text-slate-500">Evidence unavailable (access denied or expired).</p>;
  if (!src) return <div className="bg-black/20 rounded-lg p-8 flex items-center justify-center text-slate-500"><Loader2 size={24} className="animate-spin" /></div>;
  return (
    <img
      src={src}
      alt={alt}
      className="w-full h-auto object-cover opacity-80 group-hover:opacity-100 transition-opacity"
      onError={() => setError(true)}
    />
  );
};

export default function CaseReport() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState('');
  const [reason, setReason] = useState('');
  const caseLabel = `Case #${(id ?? '').toString().padStart(4, '0')}`;

  useEffect(() => {
    const fetchCase = async () => {
      try {
        const res = await api.get(`/cases/${id}`);
        setData(res.data);
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
    return <div className="flex h-64 items-center justify-center text-slate-400"><Loader2 className="animate-spin mr-2" /> Loading case report...</div>;
  }

  if (!data || !data.case) {
    return <div className="text-center text-danger mt-10">Case not found.</div>;
  }

  const { case: c, extracted_fields, module_results } = data;
  
  // Find specific modules (audit P2 §5: render ALL)
  const findModule = (name) => module_results.find(m => m.module_name === name);
  const geminiModule = findModule('gemini_ai');
  const tamperModule = findModule('tamper');
  const deepfakeModule = findModule('deepfake');
  const livenessModule = findModule('liveness');
  const checksumModule = findModule('checksum');
  const watchlistModule = findModule('watchlist');
  
  const geminiData = geminiModule?.raw_output || {};
  const faceMatch = geminiData.three_way_face_match || {};

  // A genuine registry comparison exists only when the backend actually
  // matched a citizen using trusted extraction (real Gemini or real local OCR)
  // — reported by the case API as db_record_found.
  const hasGenuineDbRecord = Boolean(data.db_record_found);

  return (
    <div className="space-y-6 animate-fade-in pb-12">
      <SEO
        title={caseLabel}
        description={`Forensic screening report for ${caseLabel}: demographic parity, 3-way face verification, tamper and deepfake analysis, liveness and watchlist results.`}
        path={`/case/${id}`}
        noindex
      />
      <Breadcrumbs items={[{ label: 'Home', to: '/' }, { label: 'Cases', to: '/' }, { label: caseLabel }]} />
      <div className="flex items-start gap-3 sm:items-center sm:gap-4">
        <button onClick={() => navigate('/')} aria-label="Back to case dashboard" className="p-2 text-slate-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors">
          <ArrowLeft size={24} />
        </button>
        <div className="min-w-0">
          <h1 className="flex flex-col gap-2 text-2xl font-bold text-white sm:flex-row sm:items-center sm:gap-3">
            {caseLabel}
            <span className="inline-flex w-fit items-center gap-2 rounded border border-slate-700 bg-slate-800 px-2.5 py-1 text-sm font-normal text-slate-300">
              <FileText size={14} /> {c.document_type?.toUpperCase() || 'UNKNOWN'}
            </span>
          </h1>
          <p className="text-slate-400 text-sm mt-1">{new Date(c.timestamp).toLocaleString()}</p>
        </div>
      </div>

      <VerdictBanner verdict={c.verdict || 'Unknown'} />

      {/* Demo-only: simulated AI was excluded from scoring */}
      {(data.is_demo || geminiModule?.is_mocked) && (
        <div className="flex items-start gap-4 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 sm:p-6">
          <ShieldAlert size={24} className="text-amber-400 shrink-0 mt-0.5" />
          <div>
            <h2 className="text-lg font-bold text-amber-400">DEMO ONLY — Simulated AI Excluded</h2>
            <p className="text-sm text-amber-200/80 mt-1">
              {data.demo_label || geminiData.is_demo && 'This case used offline simulation for face/tamper AI. Those simulated results were excluded from the risk score — this verdict is DEMO ONLY and requires manual officer review.'}
              {!data.demo_label && !geminiData.is_demo && 'Gemini AI was offline, so face/tamper results are simulated and were excluded from scoring. Manual review required.'}
            </p>
          </div>
        </div>
      )}

      {/* No DB record / unverifiable — alert the officer instead of faking a comparison */}
      {!hasGenuineDbRecord && (
        <div className="flex items-start gap-4 rounded-xl border border-warning/50 bg-warning/10 p-4 sm:p-6">
          <AlertTriangle size={24} className="text-warning shrink-0 mt-0.5" />
          <div>
            <h2 className="text-lg font-bold text-warning">NO DOCUMENT FOUND IN THE DATABASE</h2>
            <p className="text-sm text-warning/80 mt-1">
              No matching record exists in the citizens registry for this document, or the
              document could not be read automatically. The identity could not be verified
              against the database — manual verification by the officer/supervisor is required.
            </p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        {/* Demographic Parity Panel */}
        <div className="glass-panel p-4 sm:p-6">
          <div className="mb-4 flex flex-wrap items-center gap-2 border-b border-slate-700/50 pb-4">
            <User className="text-primary" size={20} />
            <h2 className="text-lg font-semibold text-white">Demographic Parity</h2>
            {!hasGenuineDbRecord && (
              <span className="rounded border border-warning/30 bg-warning/20 px-2 py-1 text-xs font-medium text-warning sm:ml-auto">
                NO DB RECORD
              </span>
            )}
          </div>

          {!hasGenuineDbRecord && (
            <div className="mb-4 p-3 bg-warning/5 border border-warning/20 text-warning rounded-lg text-sm">
              No database record is available to compare against. The officer must
              verify this identity manually against the document.
            </div>
          )}
          
          <div className="overflow-x-auto">
            <table className="w-full min-w-[620px] text-left text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-700/50">
                  <th className="py-2 font-medium">Field</th>
                  <th className="py-2 font-medium">Extracted</th>
                  <th className="py-2 font-medium">Database</th>
                  <th className="py-2 font-medium text-center">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/30">
                {extracted_fields.map(f => (
                  <tr key={f.id} className="text-slate-300">
                    <td className="py-3 pr-4">{f.field_name}</td>
                    <td className="py-3 pr-4 font-mono text-xs">{f.extracted_value || '-'}</td>
                    <td className="py-3 pr-4 font-mono text-xs">{f.database_value || '-'}</td>
                    <td className="py-3 flex justify-center">
                      {f.match_status === 'match' ? (
                        <span className="bg-success/20 text-success p-1 rounded"><Check size={16} /></span>
                      ) : f.match_status === 'mismatch' ? (
                        <span className="bg-danger/20 text-danger p-1 rounded"><X size={16} /></span>
                      ) : (
                        <span className="bg-slate-700 text-slate-400 px-2 py-1 rounded text-xs">N/A</span>
                      )}
                    </td>
                  </tr>
                ))}
                {extracted_fields.length === 0 && (
                  <tr><td colSpan={4} className="py-6 text-center text-slate-500 text-sm">No demographic data extracted.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* AI Forensic Panel — 3-Way Face Match */}
        <div className="space-y-6">
          <div className="glass-panel p-4 sm:p-6">
            <div className="mb-4 flex flex-wrap items-center gap-2 border-b border-slate-700/50 pb-4">
              <Scan className="text-accent" size={20} />
              <h2 className="text-lg font-semibold text-white">3-Way Face Match</h2>
              {geminiModule && !geminiModule.is_mocked && <StatusBadge status={geminiModule.status} />}
            </div>
            
            {!geminiModule || geminiModule.status === 'inconclusive' || geminiModule.is_mocked ? (
              <div className="bg-warning/5 border border-warning/20 p-4 rounded-lg text-sm text-warning">
                <AlertTriangle size={16} className="inline mr-2" />
                {geminiModule?.is_mocked
                  ? 'AI face verification is unavailable in this environment. No simulated results are displayed during document verification.'
                  : 'AI module was inconclusive. Face verification results are not available.'}
              </div>
            ) : (
              <>
                <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div className="flex items-center justify-between rounded-lg border border-slate-700/50 bg-black/30 p-4">
                    <span className="text-sm text-slate-400">Live vs Doc</span>
                    {faceMatch.live_vs_doc_match === true ? <span className="text-success flex items-center gap-1 text-sm font-medium"><Check size={16}/> Match</span> : 
                     faceMatch.live_vs_doc_match === false ? <span className="text-danger flex items-center gap-1 text-sm font-medium"><X size={16}/> Mismatch</span> : 
                     <span className="text-slate-500 text-sm">N/A</span>}
                  </div>
                  <div className="flex items-center justify-between rounded-lg border border-slate-700/50 bg-black/30 p-4">
                    <span className="text-sm text-slate-400">Doc vs DB</span>
                    {faceMatch.doc_vs_db_match === true ? <span className="text-success flex items-center gap-1 text-sm font-medium"><Check size={16}/> Match</span> : 
                     faceMatch.doc_vs_db_match === false ? <span className="text-danger flex items-center gap-1 text-sm font-medium"><X size={16}/> Mismatch</span> : 
                     <span className="text-slate-500 text-sm">N/A</span>}
                  </div>
                  <div className="flex items-center justify-between rounded-lg border border-slate-700/50 bg-black/30 p-4">
                    <span className="text-sm text-slate-400">Live vs DB</span>
                    {faceMatch.live_vs_db_match === true ? <span className="text-success flex items-center gap-1 text-sm font-medium"><Check size={16}/> Match</span> : 
                     faceMatch.live_vs_db_match === false ? <span className="text-danger flex items-center gap-1 text-sm font-medium"><X size={16}/> Mismatch</span> : 
                     <span className="text-slate-500 text-sm">N/A</span>}
                  </div>
                  <div className="flex flex-col justify-center rounded-lg border border-slate-700/50 bg-black/30 p-4 text-center">
                    <span className="text-xs text-slate-400 mb-1">AI Similarity Score</span>
                    <span className="text-2xl font-bold text-white">{faceMatch.similarity_score != null ? `${(faceMatch.similarity_score * 100).toFixed(1)}%` : 'N/A'}</span>
                  </div>
                </div>
                
                {faceMatch.visual_reasoning && (
                  <div className="bg-primary/5 border border-primary/20 p-4 rounded-lg">
                    <h3 className="text-xs font-semibold text-primary uppercase tracking-wider mb-2">Forensic Reasoning</h3>
                    <p className="text-sm text-slate-300 leading-relaxed">{faceMatch.visual_reasoning}</p>
                  </div>
                )}
              </>
            )}
          </div>

          {/* Tamper Detection */}
          <div className="glass-panel p-4 sm:p-6">
            <div className="mb-4 flex flex-col gap-3 border-b border-slate-700/50 pb-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2">
                <Activity className="text-warning" size={20} />
                <h2 className="text-lg font-semibold text-white">Tamper Detection</h2>
              </div>
              {tamperModule && <StatusBadge status={tamperModule.status} score={tamperModule.score} />}
            </div>
            {tamperModule?.evidence_uri ? (
              <div className="relative rounded-lg overflow-hidden border border-slate-700 group">
                <EvidenceImage
                  evidenceUri={tamperModule.evidence_uri}
                  alt="Error Level Analysis heatmap overlay highlighting suspected tampered regions of the submitted identity document"
                />
                <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent pointer-events-none flex items-end p-4">
                   <p className="text-xs text-white">ELA Heatmap Overlay</p>
                </div>
              </div>
            ) : (
              <div className="bg-black/20 rounded-lg p-8 flex flex-col items-center justify-center text-slate-500 border border-slate-700 border-dashed">
                <ImageIcon size={32} className="mb-2 opacity-50" />
                <p className="text-sm">{tamperModule?.status === 'inconclusive' ? 'Tamper analysis was inconclusive.' : 'No visual evidence generated.'}</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Additional Module Panels — Deepfake, Liveness, Checksum (audit P2 §5) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">

        {/* Deepfake Detection */}
        <div className="glass-panel p-4 sm:p-6">
          <div className="flex items-center gap-2 mb-4 border-b border-slate-700/50 pb-4">
            <Fingerprint className="text-purple-400" size={20} />
            <h2 className="text-base font-semibold text-white">Deepfake Detection</h2>
          </div>
          {deepfakeModule ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-slate-400">Status</span>
                <StatusBadge status={deepfakeModule.status} score={deepfakeModule.score} />
              </div>
              {deepfakeModule.raw_output?.method && (
                <div className="text-xs text-slate-500">
                  Method: {deepfakeModule.raw_output.method}
                </div>
              )}
              {deepfakeModule.raw_output?.metrics && (
                <div className="bg-black/20 rounded p-3 space-y-1">
                  <div className="flex justify-between gap-3 text-xs">
                    <span className="text-slate-400">HF Fraction</span>
                    <span className="text-slate-300 font-mono">{deepfakeModule.raw_output.metrics.high_frequency_fraction?.toFixed(4)}</span>
                  </div>
                  <div className="flex justify-between gap-3 text-xs">
                    <span className="text-slate-400">Spectral Peakedness</span>
                    <span className="text-slate-300 font-mono">{deepfakeModule.raw_output.metrics.spectral_peakedness?.toFixed(4)}</span>
                  </div>
                  <div className="flex justify-between gap-3 text-xs">
                    <span className="text-slate-400">Rolloff Ratio</span>
                    <span className="text-slate-300 font-mono">{deepfakeModule.raw_output.metrics.rolloff_ratio?.toFixed(4)}</span>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-slate-500">No deepfake analysis available.</p>
          )}
        </div>

        {/* Liveness Detection */}
        <div className="glass-panel p-4 sm:p-6">
          <div className="flex items-center gap-2 mb-4 border-b border-slate-700/50 pb-4">
            <Eye className="text-cyan-400" size={20} />
            <h2 className="text-base font-semibold text-white">Liveness Detection</h2>
          </div>
          {livenessModule ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-slate-400">Status</span>
                <StatusBadge status={livenessModule.status} score={livenessModule.score} />
              </div>
              {livenessModule.raw_output?.live !== undefined && (
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm text-slate-400">Result</span>
                  {livenessModule.raw_output.live ? (
                    <span className="text-success flex items-center gap-1 text-sm font-medium"><Radio size={14}/> Live</span>
                  ) : (
                    <span className="text-danger flex items-center gap-1 text-sm font-medium"><X size={14}/> Spoof Suspected</span>
                  )}
                </div>
              )}
              {livenessModule.raw_output?.blink_count !== undefined && (
                <div className="bg-black/20 rounded p-3 space-y-1">
                  <div className="flex justify-between gap-3 text-xs">
                    <span className="text-slate-400">Blink Count</span>
                    <span className="text-slate-300 font-mono">{livenessModule.raw_output.blink_count}</span>
                  </div>
                  <div className="flex justify-between gap-3 text-xs">
                    <span className="text-slate-400">Frames Analysed</span>
                    <span className="text-slate-300 font-mono">{livenessModule.raw_output.frames_analysed}</span>
                  </div>
                  {livenessModule.raw_output?.ear_stats && (
                    <div className="flex justify-between gap-3 text-xs">
                      <span className="text-slate-400">EAR Swing</span>
                      <span className="text-slate-300 font-mono">{livenessModule.raw_output.ear_stats.swing?.toFixed(4)}</span>
                    </div>
                  )}
                </div>
              )}
              {livenessModule.status === 'inconclusive' && (
                <div className="text-xs text-warning bg-warning/5 border border-warning/20 p-2 rounded">
                  {livenessModule.raw_output?.reason || 'Liveness check was inconclusive. A multi-frame burst is required for reliable detection.'}
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-slate-500">No liveness data available.</p>
          )}
        </div>

        {/* Checksum Validation */}
        <div className="glass-panel p-4 sm:p-6">
          <div className="flex items-center gap-2 mb-4 border-b border-slate-700/50 pb-4">
            <Hash className="text-emerald-400" size={20} />
            <h2 className="text-base font-semibold text-white">Checksum Validation</h2>
          </div>
          {checksumModule ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-slate-400">Document Type</span>
                <span className="text-sm text-slate-300">{checksumModule.raw_output?.document_type?.toUpperCase() || '-'}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-slate-400">Valid</span>
                {checksumModule.raw_output?.valid === true ? (
                  <span className="text-success flex items-center gap-1 text-sm font-medium"><Check size={16}/> Pass</span>
                ) : checksumModule.raw_output?.valid === false ? (
                  <span className="text-danger flex items-center gap-1 text-sm font-medium"><X size={16}/> Fail</span>
                ) : (
                  <span className="text-xs px-2 py-1 bg-slate-700/40 text-slate-300 rounded border border-slate-600">N/A — not digitally verifiable</span>
                )}
              </div>
              {checksumModule.raw_output?.algorithm && (
                <div className="text-xs text-slate-500">
                  Algorithm: {checksumModule.raw_output.algorithm}
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-slate-500">No checksum data available.</p>
          )}
        </div>
      </div>

      {/* Watchlist Panel — always shown, even on clear (audit P2 §6) */}
      <div className={`glass-panel p-4 sm:p-6 ${!watchlistModule?.is_mocked && watchlistModule?.raw_output?.is_hit ? 'border-danger/50 bg-danger/5' : 'bg-black/5'}`}>
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <ShieldAlert className={!watchlistModule?.is_mocked && watchlistModule?.raw_output?.is_hit ? 'text-danger' : 'text-slate-400'} size={24} />
          <h2 className="text-lg font-semibold text-white">
            Watchlist Lookup
          </h2>
          {!watchlistModule?.is_mocked && (watchlistModule?.raw_output?.is_hit ? (
            <span className="ml-2 bg-danger/20 text-danger px-2 py-1 rounded text-xs font-medium border border-danger/30">HIT</span>
          ) : (
            <span className="ml-2 bg-success/20 text-success px-2 py-1 rounded text-xs font-medium border border-success/30">CLEAR</span>
          ))}
        </div>
        {watchlistModule?.is_mocked ? (
          <p className="text-sm text-slate-400">
            Watchlist registry is not connected. Lookout results are unavailable and were not used in this screening.
          </p>
        ) : watchlistModule?.raw_output?.is_hit ? (
          <div className="space-y-2">
            {watchlistModule.raw_output.hits.map((hit, i) => (
              <div key={i} className="bg-black/40 p-4 rounded-lg border border-danger/20">
                <p className="text-sm font-medium text-white">{hit.name} <span className="ml-0 block text-slate-500 sm:ml-2 sm:inline">ID: {hit.id_number}</span></p>
                <p className="text-sm text-danger mt-1">{hit.source}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-400">No watchlist matches found for this traveler.</p>
        )}
      </div>

      {/* Officer Action — state machine: pending_review -> escalated -> decided; deny requires supervisor */}
      {(() => {
        const myRole = (localStorage.getItem('role') || 'officer').toLowerCase();
        const isAuditor = myRole === 'auditor';
        const isOfficer = myRole === 'officer';
        const isSupervisor = myRole === 'supervisor';
        if (c.status === 'decided') {
          return (
            <div className="glass-panel mt-6 flex flex-col gap-4 bg-white/5 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-6">
              <div className="flex items-center gap-3 text-slate-300">
                <Shield size={20} className="text-slate-500"/>
                <span className="font-medium">Case Adjudicated</span>
              </div>
              <span className="uppercase text-sm tracking-wider bg-slate-800 px-3 py-1 rounded text-white border border-slate-700">Status: decided (v{c.version ?? 0})</span>
            </div>
          );
        }
        if (c.status === 'escalated') {
          return (
            <div className="glass-panel mt-6 border-t-4 border-t-warning p-4 sm:p-6">
              <div className="flex items-center gap-2 mb-4 text-warning">
                <AlertTriangle size={20} />
                <h2 className="text-lg font-semibold">Escalated — Awaiting Supervisor Decision</h2>
              </div>
              <p className="text-sm text-slate-400 mb-4">This case was escalated for supervisor review. Only a supervisor can clear or deny it.</p>
              {isAuditor ? (
                <p className="text-sm text-slate-500">Auditor role is read-only.</p>
              ) : isOfficer ? (
                <p className="text-sm text-slate-500">Your role cannot decide escalated cases.</p>
              ) : (
                <div className="space-y-4">
                  <label htmlFor="adjudication-reason" className="block text-sm font-medium text-slate-300">
                    Decision justification <span className="text-slate-500">(required, minimum 3 characters)</span>
                  </label>
                  <textarea id="adjudication-reason" value={reason} onChange={(e) => setReason(e.target.value)} className="w-full bg-black/20 border border-slate-700 rounded-lg p-4 text-white focus:outline-none focus:border-primary transition-colors text-sm min-h-[100px]" placeholder="Record the grounds for this decision..." />
                  {actionError && (<div role="alert" className="bg-danger/10 border border-danger/50 text-danger rounded-lg p-3 text-sm">{actionError}</div>)}
                  <div className="flex flex-col gap-3 sm:flex-row sm:gap-4">
                    <button onClick={() => handleAction('clear')} disabled={actionLoading} className="flex-1 bg-success/10 hover:bg-success/20 text-success border border-success/30 py-3 rounded-lg font-medium transition-colors flex items-center justify-center gap-2"><CheckCircle size={18} /> Clear Traveler</button>
                    <button onClick={() => handleAction('deny')} disabled={actionLoading} className="flex-1 bg-danger/10 hover:bg-danger/20 text-danger border border-danger/30 py-3 rounded-lg font-medium transition-colors flex items-center justify-center gap-2"><X size={18} /> Deny Entry</button>
                  </div>
                </div>
              )}
            </div>
          );
        }
        // pending_review
        return (
          <div className="glass-panel mt-6 border-t-4 border-t-primary p-4 sm:p-6">
            <h2 className="text-lg font-semibold text-white mb-4">Officer Adjudication <span className="text-xs font-normal text-slate-500">(v{c.version ?? 0})</span></h2>
            <div className="space-y-4">
              <label htmlFor="adjudication-reason" className="block text-sm font-medium text-slate-300">
                Decision justification <span className="text-slate-500">(required, minimum 3 characters)</span>
              </label>
              <textarea id="adjudication-reason" value={reason} onChange={(e) => setReason(e.target.value)} className="w-full bg-black/20 border border-slate-700 rounded-lg p-4 text-white focus:outline-none focus:border-primary transition-colors text-sm min-h-[100px]" placeholder="Record the grounds for this decision..." />
              {actionError && (<div role="alert" className="bg-danger/10 border border-danger/50 text-danger rounded-lg p-3 text-sm">{actionError}</div>)}
              <div className="flex flex-col gap-3 sm:flex-row sm:gap-4">
                <button onClick={() => handleAction('clear')} disabled={actionLoading} className="flex-1 bg-success/10 hover:bg-success/20 text-success border border-success/30 py-3 rounded-lg font-medium transition-colors flex items-center justify-center gap-2"><CheckCircle size={18} /> Clear Traveler</button>
                {isOfficer ? (
                  <button disabled className="flex-1 bg-slate-800 text-slate-500 border border-slate-700 py-3 rounded-lg font-medium flex items-center justify-center gap-2 cursor-not-allowed" title="Deny requires supervisor approval — use Escalate"><X size={18} /> Deny (Supervisor Only)</button>
                ) : (
                  <button onClick={() => handleAction('deny')} disabled={actionLoading || isAuditor} className="flex-1 bg-danger/10 hover:bg-danger/20 text-danger border border-danger/30 py-3 rounded-lg font-medium transition-colors flex items-center justify-center gap-2 disabled:opacity-50"><X size={18} /> Deny Entry</button>
                )}
                <button onClick={() => handleAction('escalate')} disabled={actionLoading || isAuditor} className="flex-1 bg-warning/10 hover:bg-warning/20 text-warning border border-warning/30 py-3 rounded-lg font-medium transition-colors flex items-center justify-center gap-2 disabled:opacity-50"><Shield size={18} /> Escalate to Supervisor</button>
              </div>
              {isAuditor && <p className="text-xs text-slate-500">Auditor is read-only.</p>}
            </div>
          </div>
        );
      })()}
    </div>
  );
}
