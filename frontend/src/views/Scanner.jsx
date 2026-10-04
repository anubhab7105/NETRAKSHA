import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Camera, Loader2, ScanLine, RefreshCw, X, Video, Image as ImageIcon, AlertTriangle, CheckCircle2 } from 'lucide-react';
import api, { apiErrorMessage } from '../api';
import SEO from '../components/SEO';
import Breadcrumbs from '../components/Breadcrumbs';
import { PageHeader, WorkflowSteps, GovNotice } from '../components/ui';

function WebcamCapture({ label, hint, facing, subject, file, onCapture, onClear, stepNo }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const retakeTimerRef = useRef(null);
  const [previewing, setPreviewing] = useState(false);
  const [starting, setStarting] = useState(false);
  const [videoReady, setVideoReady] = useState(false);
  const [bursting, setBursting] = useState(false);
  const [error, setError] = useState(null);
  const urlRef = useRef(null);
  const previewUrl = React.useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);

  useEffect(() => {
    if (urlRef.current && urlRef.current !== previewUrl) {
      URL.revokeObjectURL(urlRef.current);
    }
    urlRef.current = previewUrl;
    return () => {
      if (urlRef.current) {
        URL.revokeObjectURL(urlRef.current);
        urlRef.current = null;
      }
    };
  }, [previewUrl]);

  useEffect(() => {
    if (previewing && videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
      videoRef.current.play().catch(() => {});
    }
  }, [previewing, file]);

  const stopStream = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setVideoReady(false);
    setPreviewing(false);
  };

  useEffect(() => {
    return () => {
      if (retakeTimerRef.current) clearTimeout(retakeTimerRef.current);
      stopStream();
    };
  }, []);

  const startCamera = async () => {
    setStarting(true);
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: facing } },
        audio: false,
      });
      streamRef.current = stream;
      setPreviewing(true);
    } catch (err) {
      setError(
        err && err.name === 'NotAllowedError'
          ? 'Camera permission denied. Allow webcam access in your browser and try again.'
          : 'Unable to access the webcam. Ensure a camera is connected and try again.'
      );
    } finally {
      setStarting(false);
    }
  };

  const handleRetake = () => {
    if (retakeTimerRef.current) clearTimeout(retakeTimerRef.current);
    stopStream();
    setBursting(false);
    setError(null);
    onClear();
    retakeTimerRef.current = setTimeout(() => {
      retakeTimerRef.current = null;
      startCamera();
    }, 300);
  };

  const capturePhoto = async () => {
    const video = videoRef.current;
    if (!video || video.videoWidth === 0) {
      setError('Camera preview is not ready yet. Try again.');
      return;
    }
    const vw = video.videoWidth || 1280;
    const vh = video.videoHeight || 720;
    const scale = Math.min(1, 1280 / Math.max(vw, vh));
    const w = Math.max(2, Math.round(vw * scale));
    const h = Math.max(2, Math.round(vh * scale));
    // Sequential capture on a dedicated canvas per shot: awaiting each
    // toBlob BEFORE the next drawImage avoids the classic race where N
    // pending toBlob promises all resolve with the LAST drawn frame.
    const snap = () => new Promise((resolve) => {
      const canvas = document.createElement('canvas');
      canvas.width = w;
      canvas.height = h;
      canvas.getContext('2d').drawImage(video, 0, 0, w, h);
      canvas.toBlob((blob) => resolve(blob), 'image/jpeg', 0.85);
    });
    const blob = await snap();
    if (!blob) {
      setError('Capture failed. Please try again.');
      return;
    }
    const captured = new File([blob], `${subject === 'document' ? 'document_capture' : 'live_capture'}.jpg`, { type: 'image/jpeg' });
    onCapture(captured);
    stopStream();
  };

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <p className="mb-2 flex items-center gap-2 text-sm font-semibold text-[#172033]">
        <span className="gov-step-dot gov-step-current" aria-hidden="true">{stepNo}</span>
        {label}
      </p>
      <div className={`flex min-h-[260px] flex-col rounded-lg border-2 border-dashed bg-white p-4 text-center sm:min-h-[280px] sm:p-5 ${file ? 'border-[#16803C] bg-[#EAF6EE]/40' : 'border-[#BEC6D5] hover:border-[#1769AA]'}`}>
        {file ? (
          <div className="flex flex-1 flex-col items-center justify-center">
            {previewUrl && (
              <img
                src={previewUrl}
                alt={subject === 'document' ? 'Captured identity document preview' : 'Captured live face preview'}
                className="mb-3 max-h-[180px] max-w-full rounded-lg border border-[#D9DEE7] bg-[#F7F8FA] object-contain"
              />
            )}
            <p className="flex items-center gap-1.5 text-sm font-semibold text-[#16803C]">
              <CheckCircle2 size={15} aria-hidden="true" /> Captured
            </p>
            <p className="mt-1 max-w-full truncate text-sm font-medium text-[#172033] sm:max-w-[260px]">{file.name}</p>
            <p className="mt-1 text-xs text-[#98A2B3]">{(file.size / 1024).toFixed(1)} KB</p>
            <div className="mt-4 flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
              <button
                type="button"
                onClick={() => { stopStream(); onClear(); }}
                className="gov-btn gov-btn-secondary min-h-[36px]! px-3! py-2! text-[13px]!"
              >
                <X size={14} aria-hidden="true" />
                Clear
              </button>
              <button
                type="button"
                onClick={handleRetake}
                className="gov-btn gov-btn-secondary min-h-[36px]! px-3! py-2! text-[13px]!"
              >
                <RefreshCw size={14} aria-hidden="true" />
                Retake
              </button>
            </div>
          </div>
        ) : previewing ? (
          <>
            <div className="relative">
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              onLoadedMetadata={() => setVideoReady(true)}
              className="h-[180px] w-full rounded-lg border border-[#D9DEE7] bg-[#172033] object-contain sm:h-[220px] md:h-[180px]"
            />
            {bursting && (
              <div className="absolute inset-0 flex flex-col items-center justify-center rounded-lg bg-[#172033]/80">
                <p className="px-4 text-center font-bold text-white">Follow the prompt — Blink / Turn Head / Open Mouth</p>
                <p className="mt-1 text-xs text-white/75">Active liveness challenge — capturing face motion…</p>
              </div>
            )}
          </div>
            <p className="mt-2 text-xs text-[#667085]">{hint}</p>
            {error && <p className="mt-2 text-xs font-medium text-[#C62828]" role="alert">{error}</p>}
            <div className="mt-3 flex flex-col items-stretch justify-center gap-2 sm:flex-row sm:items-center">
              <button
                type="button"
                onClick={stopStream}
                className="gov-btn gov-btn-secondary min-h-[36px]! px-3! py-2! text-[13px]!"
              >
                <X size={14} aria-hidden="true" />
                Cancel
              </button>
              <button
                type="button"
                onClick={capturePhoto}
                disabled={!videoReady || bursting}
                className="gov-btn gov-btn-primary min-h-[36px]! px-4! py-2! text-[13px]!"
              >
                {bursting ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <Camera size={14} aria-hidden="true" />}
                {bursting ? 'Capturing…' : 'Capture Photo'}
              </button>
            </div>
          </>
        ) : (
          <button type="button" onClick={startCamera} disabled={starting} className="group flex flex-1 cursor-pointer flex-col items-center justify-center disabled:opacity-60">
            {starting ? (
              <Loader2 size={30} className="mb-3 animate-spin text-[#98A2B3]" aria-hidden="true" />
            ) : (
              <div className="mb-3 rounded-full border border-[#D9DEE7] bg-[#F1F4F9] p-3 text-[#667085] transition-colors group-hover:border-[#1769AA] group-hover:text-[#1769AA]" aria-hidden="true">
                {subject === 'document' ? <ImageIcon size={28} /> : <Video size={28} />}
              </div>
            )}
            <p className="text-sm font-semibold text-[#172033]">
              {starting ? 'Opening webcam…' : 'Click to open webcam'}
            </p>
            <p className="mt-1 text-xs text-[#667085]">{hint}</p>
            {error && <p className="mt-2 text-xs font-medium text-[#C62828]" role="alert">{error}</p>}
          </button>
        )}
      </div>
    </div>
  );
}

import PersonBiometricCapture from '../components/PersonBiometricCapture';

export default function Scanner() {
  const [docFile, setDocFile] = useState(null);
  const [personCapture, setPersonCapture] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState(null);
  const navigate = useNavigate();
  const scanAbortRef = useRef(null);

  useEffect(() => () => {
    if (scanAbortRef.current) scanAbortRef.current.abort();
  }, []);

  
  
  
  const IDEMPOTENCY_STORE_KEY = 'scan:idempotency-key';
  const newIdempotencyKey = () => {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
    if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
      const b = crypto.getRandomValues(new Uint8Array(16));
      b[6] = (b[6] & 0x0f) | 0x40;
      b[8] = (b[8] & 0x3f) | 0x80;
      const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('');
      return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
    }
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}-${Math.random().toString(36).slice(2, 10)}`;
  };
  // Per-intent UUID persisted in sessionStorage so a reload mid-intent reuses
  // the same key (safe retry) instead of minting a duplicate screening.
  const [idempotencyKey, setIdempotencyKey] = useState(() => {
    try {
      const saved = sessionStorage.getItem(IDEMPOTENCY_STORE_KEY);
      if (saved) return saved;
    } catch { /* private mode — fall through */ }
    const fresh = newIdempotencyKey();
    try { sessionStorage.setItem(IDEMPOTENCY_STORE_KEY, fresh); } catch { /* ignore */ }
    return fresh;
  });
  const rotateIdempotencyKey = useCallback(() => {
    const fresh = newIdempotencyKey();
    try { sessionStorage.setItem(IDEMPOTENCY_STORE_KEY, fresh); } catch { /* ignore */ }
    setIdempotencyKey(fresh);
  }, []);


  useEffect(() => {
    rotateIdempotencyKey();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docFile, personCapture]);

  const handleScan = async () => {
    if (!docFile) {
      setError("Please capture a document image using the webcam.");
      return;
    }

    const MAX_DOC_BYTES = 10_000_000;
    const MAX_LIVE_BYTES = 5_000_000;
    const MAX_FRAMES = 10;
    const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
    if (docFile.size > MAX_DOC_BYTES) {
      setError("Document image too large (max 10 MB). Retake with a lower resolution.");
      return;
    }
    if (docFile.type && !ALLOWED_TYPES.includes(docFile.type)) {
      setError("Document image must be JPEG, PNG or WEBP.");
      return;
    }
    const burstCheck = Array.isArray(personCapture?.burst) ? personCapture.burst : [];
    if (burstCheck.length > MAX_FRAMES) {
      setError(`Too many live frames (max ${MAX_FRAMES}). Retake the biometric capture.`);
      return;
    }
    for (const b of burstCheck) {
      if ((b?.size || 0) > MAX_LIVE_BYTES || (b?.type && !ALLOWED_TYPES.includes(b.type))) {
        setError("A live frame is oversized or not an image. Retake the biometric capture.");
        return;
      }
    }
    if (typeof window !== 'undefined' && window.isSecureContext === false) {
      setError("Camera capture requires a secure context (HTTPS or localhost). Serve the app over HTTPS.");
      return;
    }

    setScanning(true);
    setError(null);

    const formData = new FormData();
    formData.append('document_image', docFile);
    
    
    formData.append('idempotency_key', idempotencyKey);
    if (personCapture) {
      
      
      
      
      
      const burst = Array.isArray(personCapture.burst) ? personCapture.burst : [];
      const primary = personCapture.primaryFrame || burst[Math.floor(burst.length / 2)] || burst[0];
      const primaryType = primary?.type || 'image/jpeg';
      const primaryExt = primaryType.includes('png') ? 'png' : 'jpg';
      if (primary) {
        formData.append('live_capture', new File([primary], `live_capture.${primaryExt}`, { type: primaryType }));
      }
      burst.forEach((b, i) => {
        const t = b?.type || 'image/jpeg';
        formData.append('live_frames', new File([b], `live_frame_${i}.${t.includes('png') ? 'png' : 'jpg'}`, { type: t }));
      });
      formData.append('iris_eye', personCapture.eyeHint || 'auto');
    }

    try {
      if (scanAbortRef.current) scanAbortRef.current.abort();
      const controller = new AbortController();
      scanAbortRef.current = controller;
      const res = await api.post('/screen', formData, {
        headers: {
          
          'Idempotency-Key': idempotencyKey,
        },
        signal: controller.signal,
      });
      // Intent complete — mint the next key so a re-scan never replays this case.
      rotateIdempotencyKey();
      navigate(`/case/${res.data.case_id}`);
    } catch (err) {
      if (err?.code === 'ERR_CANCELED') {
        setScanning(false);
        return;
      }
      if (import.meta.env.DEV) console.error(err);
      const status = err.response?.status;
      const rawDetail = err.response?.data?.detail;
      const detail = typeof rawDetail === 'string' ? rawDetail : rawDetail ? JSON.stringify(rawDetail, null, 2) : (typeof err.response?.data === 'string' ? err.response.data : null);
      
      const isDocQuality = rawDetail && typeof rawDetail === 'object' && rawDetail.error === 'document_quality_failed';
      if (status === 409) {
        
        
        setError(
          detail
            ? `Duplicate suppressed (HTTP 409): ${detail}`
            : 'This screening is already in progress. Please wait for the original request to finish.'
        );
        setScanning(false);
        return;
      }
      if (status === 422 && /idempo/i.test(String(detail || ''))) {
        // Key rejected — rotate so the retry cannot replay the bad key.
        rotateIdempotencyKey();
        setError(
          detail
            ? `Screening failed (HTTP 422): ${detail} A fresh idempotency key was generated — please retry.`
            : 'Screening failed: idempotency key mismatch. A fresh key was generated — please retry.'
        );
        setScanning(false);
        return;
      }
      if (isDocQuality) {
        const reasons = (rawDetail.recapture_reasons || []).join(', ') || 'low quality';
        setError(`Document quality too low (${reasons}). Please recapture in good light, hold steady, and ensure the document fills the frame.`);
        setScanning(false);
        return;
      }
      setError(
        detail
          ? `Screening failed (HTTP ${err.response.status}): ${typeof detail === 'string' ? detail.slice(0, 500) : apiErrorMessage(err)}`
          : err.request && !err.response
            ? `Screening failed: could not reach the backend at ${api.defaults.baseURL || '/api'}. Check VITE_API_BASE_URL and backend CORS, then retry.`
            : apiErrorMessage(err, 'Screening failed. Please ensure the backend is running and try again.')
      );
      setScanning(false);
    }
  };

  const ready = Boolean(docFile);

  return (
    <div className="mx-auto max-w-5xl animate-fade-in space-y-5">
      <SEO
        title="Kiosk Scanner"
        description="Capture an identity document and the traveler’s live face to run the full forensic screening pipeline and receive a composite risk verdict."
        path="/scan"
      />
      <Breadcrumbs items={[{ label: 'Overview', to: '/' }, { label: 'New Verification' }]} />
      <PageHeader
        title="New Verification"
        subtitle="Capture the identity document, then capture the traveler once — one person capture feeds face, liveness and iris."
      />

      <section aria-label="Verification workflow" className="gov-card-padded">
        <h2 className="gov-card-title">Verification Workflow</h2>
        <p className="gov-meta mt-0.5">Stages run automatically after you initiate screening. Technical evidence appears in the case report.</p>
        <div className="mt-4">
          <WorkflowSteps activeIndex={scanning ? 4 : 0} />
        </div>
      </section>

      {error && (
        <GovNotice tone="red" icon={<AlertTriangle size={18} aria-hidden="true" />} title="Screening could not be completed">
          {error}
        </GovNotice>
      )}

      <section aria-label="Evidence capture" className="gov-card-padded">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-[#D9DEE7] pb-3">
          <h2 className="gov-card-title">1 · Evidence Capture</h2>
          <span className={`gov-badge ${ready ? 'gov-badge-green' : 'gov-badge-grey'}`}>
            {ready ? 'Document ready' : 'Awaiting document'}
          </span>
        </div>
        <div className="mb-6 flex flex-col gap-6 md:flex-row">
          <WebcamCapture
            label="Document Image (Required)"
            hint="Position the identity document inside the frame"
            facing="environment"
            subject="document"
            file={docFile}
            onCapture={setDocFile}
            onClear={() => setDocFile(null)}
            stepNo="1"
          />
          <PersonBiometricCapture
            file={personCapture}
            onCapture={setPersonCapture}
            onClear={() => setPersonCapture(null)}
            facing="user"
          />
        </div>

        <div className="flex flex-col gap-3 border-t border-[#D9DEE7] pt-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-[#667085]">
            Screening runs document validation → OCR/MRZ → registry check → vision analysis → face match → demographics → risk engine.
          </p>
          <button
            type="button"
            onClick={handleScan}
            disabled={scanning || !docFile}
            className="gov-btn gov-btn-primary w-full sm:w-auto sm:min-w-[220px]"
          >
            {scanning ? (
              <>
                <Loader2 size={18} className="animate-spin" aria-hidden="true" />
                Processing…
              </>
            ) : (
              <>
                <ScanLine size={18} aria-hidden="true" />
                Initiate Screening
              </>
            )}
          </button>
        </div>
      </section>
    </div>
  );
}
