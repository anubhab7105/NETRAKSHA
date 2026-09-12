import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Camera, Loader2, Scan, RefreshCw, X, Video, Image as ImageIcon } from 'lucide-react';
import api from '../api';
import SEO from '../components/SEO';
import Breadcrumbs from '../components/Breadcrumbs';

function WebcamCapture({ label, hint, facing, subject, file, onCapture, onClear, onAllowBurst }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
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
  }, [previewing]);

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
    return () => stopStream();
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

  const capturePhoto = async () => {
    const video = videoRef.current;
    if (!video || video.videoWidth === 0) {
      setError('Camera preview is not ready yet. Try again.');
      return;
    }
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');

    // For the live-face capture, grab a ~2s frame burst so the liveness module
    // can detect a real blink (adaptive EAR), micro-motion and screen-replay
    // artifacts. A ~0.8s / 6-frame burst was too short to reliably catch a blink.
    if (onAllowBurst && subject === 'face') {
      setBursting(true);
      setError(null);
      try {
        // give the person a moment to react to the "blink now" prompt
        await new Promise((r) => setTimeout(r, 650));
        const totalFrames = 14; // ~14 * 150ms ~ 2.1s capture window
        const frames = [];
        for (let i = 0; i < totalFrames; i++) {
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          frames.push(
            new Promise((resolve) =>
              canvas.toBlob((blob) => resolve(blob), 'image/png')
            )
          );
          await new Promise((r) => setTimeout(r, 150));
        }
        const blobs = await Promise.all(frames);
        const captured = new File(blobs, `${subject}_burst.zip`, {
          type: 'application/zip',
        });
        captured.burst = blobs; // attach the frame blobs for multipart upload
        setBursting(false);
        onCapture(captured);
        stopStream();
      } catch {
        setBursting(false);
        setError('Capture interrupted. Please try again.');
      }
      return;
    }

    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      if (!blob) return;
      const captured = new File([blob], `${subject === 'document' ? 'document_capture' : 'live_capture'}.png`, { type: 'image/png' });
      onCapture(captured);
      stopStream();
    }, 'image/png');
  };

  return (
    <div className="flex-1 min-w-0">
      <label className="block text-sm font-medium text-slate-300 mb-2">{label}</label>
      <div className={`flex min-h-[260px] flex-col rounded-xl border-2 border-dashed p-4 text-center transition-all sm:min-h-[280px] sm:p-5 ${file ? 'border-success/50 bg-success/5' : 'border-slate-700 hover:border-primary/50'}`}>
        {file ? (
          <div className="flex flex-col items-center justify-center flex-1">
            {previewUrl && (
              <img
                src={previewUrl}
                alt={subject === 'document' ? 'Captured identity document preview' : 'Captured live face preview'}
                className="mb-3 max-h-[180px] max-w-full rounded-lg border border-slate-700/50 object-contain"
              />
            )}
            <p className="max-w-full truncate text-sm font-medium text-slate-200 sm:max-w-[260px]">{file.name}</p>
            <p className="text-xs text-slate-500 mt-1">{(file.size / 1024).toFixed(1)} KB</p>
            <div className="mt-4 flex w-full flex-col gap-3 sm:w-auto sm:flex-row">
              <button
                onClick={() => { stopStream(); onClear(); }}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs font-medium text-slate-400 transition-all hover:bg-slate-700 hover:text-white"
              >
                <X size={14} />
                Clear
              </button>
              <button
                onClick={startCamera}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-primary/40 bg-primary/10 px-3 py-2 text-xs font-medium text-primary transition-all hover:bg-primary/20"
              >
                <RefreshCw size={14} />
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
              className="h-[180px] w-full rounded-lg border border-slate-700/50 bg-black object-contain sm:h-[220px] md:h-[180px]"
            />
            {bursting && (
              <div className="absolute inset-0 rounded-lg bg-black/70 flex flex-col items-center justify-center">
                <p className="text-white font-bold text-lg animate-pulse">Follow the prompt — Blink / Turn Head / Open Mouth</p>
                <p className="text-slate-300 text-xs mt-1">Active liveness challenge — capturing face motion…</p>
              </div>
            )}
          </div>
            <p className="text-xs text-slate-400 mt-2">{hint}</p>
            {error && <p className="text-xs text-danger mt-2">{error}</p>}
            <div className="mt-3 flex flex-col items-stretch justify-center gap-3 sm:flex-row sm:items-center">
              <button
                onClick={stopStream}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs font-medium text-slate-400 transition-all hover:bg-slate-700 hover:text-white"
              >
                <X size={14} />
                Cancel
              </button>
              <button
                onClick={capturePhoto}
                disabled={!videoReady || bursting}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-gradient-to-r from-primary to-accent px-4 py-2 text-xs font-medium text-white transition-all hover:from-primary/90 hover:to-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {bursting ? <Loader2 size={14} className="animate-spin" /> : <Camera size={14} />}
                {bursting ? 'Capturing…' : 'Capture Photo'}
              </button>
            </div>
          </>
        ) : (
          <button onClick={startCamera} disabled={starting} className="flex-1 flex flex-col items-center justify-center group cursor-pointer disabled:opacity-60">
            {starting ? (
              <Loader2 size={32} className="animate-spin text-slate-400 mb-3" />
            ) : (
              <div className="bg-slate-800 p-3 rounded-full text-slate-400 group-hover:text-primary group-hover:bg-primary/10 transition-all mb-3">
                {subject === 'document' ? <ImageIcon size={32} /> : <Video size={32} />}
              </div>
            )}
            <p className="text-sm text-slate-300 font-medium group-hover:text-white transition-colors">
              {starting ? 'Opening webcam...' : `Click to open webcam`}
            </p>
            <p className="text-xs text-slate-500 mt-1">{hint}</p>
            {error && <p className="text-xs text-danger mt-2">{error}</p>}
          </button>
        )}
      </div>
    </div>
  );
}

import IrisCapture from '../components/IrisCapture';

export default function Scanner() {
  const [docFile, setDocFile] = useState(null);
  const [faceFile, setFaceFile] = useState(null);
  const [irisFile, setIrisFile] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  // Idempotency key: one UUID per screening intent. Reused across network
  // retries so POST /api/screen returns the original case instead of a
  // duplicate. Regenerated when inputs change or after a completed screening.
  const newIdempotencyKey = () => (
    typeof crypto !== 'undefined' && crypto.randomUUID
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}-${Math.random().toString(36).slice(2, 10)}`
  );
  const [idempotencyKey, setIdempotencyKey] = useState(() => newIdempotencyKey());

  // New inputs => new screening intent => fresh key. Otherwise the server
  // would rightly reject the old key with 422 (different input bytes).
  useEffect(() => {
    setIdempotencyKey(newIdempotencyKey());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docFile, faceFile]);

  const handleScan = async () => {
    if (!docFile) {
      setError("Please capture a document image using the webcam.");
      return;
    }

    setScanning(true);
    setError(null);

    const formData = new FormData();
    formData.append('document_image', docFile);
    // Form-field fallback mirrors the Idempotency-Key header (for proxies
    // that strip custom headers on multipart uploads).
    formData.append('idempotency_key', idempotencyKey);
    if (faceFile) {
      if (Array.isArray(faceFile.burst) && faceFile.burst.length > 0) {
        // Send the first frame as live_capture so 3-way face matching works,
        // plus the full burst as live_frames for liveness blink detection.
        const bestFrame = faceFile.burst[Math.floor(faceFile.burst.length / 2)] || faceFile.burst[0];
        formData.append('live_capture', new File([bestFrame], 'live_capture.png', { type: 'image/png' }));
        faceFile.burst.forEach((b, i) =>
          formData.append('live_frames', new File([b], `live_frame_${i}.png`, { type: 'image/png' }))
        );
      } else {
        formData.append('live_capture', faceFile);
      }
      if (irisFile) {
        formData.append('iris_image', irisFile);
        formData.append('iris_eye', irisFile.eye || 'left');
      }
    }

    try {
      const res = await api.post('/screen', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
          'Idempotency-Key': idempotencyKey,
        }
      });
      // Success (or idempotent replay) — mint a fresh key so the next
      // screening is a new intent, then go to the (original) case.
      setIdempotencyKey(newIdempotencyKey());
      navigate(`/case/${res.data.case_id}`);
    } catch (err) {
      if (import.meta.env.DEV) console.error(err);
      const status = err.response?.status;
      const detail =
        err.response?.data?.detail ||
        (typeof err.response?.data === 'string' ? err.response.data : null);
      if (status === 409) {
        // Duplicate in flight — the original request is still processing.
        // Keep the SAME key so a manual retry joins the original, not a new case.
        setError(
          detail
            ? `Duplicate suppressed (HTTP 409): ${detail}`
            : 'This screening is already in progress. Please wait for the original request to finish.'
        );
        setScanning(false);
        return;
      }
      if (status === 422 && /idempo/i.test(String(detail || ''))) {
        // Key/input drift (e.g. files changed mid-flight) — mint a fresh key
        // and ask the officer to retry once.
        setIdempotencyKey(newIdempotencyKey());
        setError(
          detail
            ? `Screening failed (HTTP 422): ${detail} A fresh idempotency key was generated — please retry.`
            : 'Screening failed: idempotency key mismatch. A fresh key was generated — please retry.'
        );
        setScanning(false);
        return;
      }
      setError(
        detail
          ? `Screening failed (HTTP ${err.response.status}): ${detail}`
          : err.request && !err.response
            ? 'Screening failed: could not reach the backend. Is uvicorn running on :8000?'
            : 'Screening failed. Please ensure the backend is running and try again.'
      );
      setScanning(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6 animate-fade-in">
      <SEO
        title="Kiosk Scanner"
        description="Capture an identity document and the traveler’s live face to run the full forensic screening pipeline and receive a composite risk verdict."
        path="/scan"
      />
      <Breadcrumbs items={[{ label: 'Home', to: '/' }, { label: 'Kiosk Scanner' }]} />
      <header>
        <h1 className="text-2xl font-bold text-white">Kiosk Simulator</h1>
        <p className="text-slate-400 text-sm mt-1">Use the webcams to capture the identity document and the traveler's live face.</p>
      </header>

      {error && (
        <div className="p-4 bg-danger/10 border border-danger/50 text-danger rounded-lg">
          {error}
        </div>
      )}

      <div className="glass-panel p-4 sm:p-6">
        <div className="flex gap-6 mb-8 flex-col md:flex-row">
          <WebcamCapture
            label="1. Document Image (Required)"
            hint="Position the identity document inside the frame"
            facing="environment"
            subject="document"
            file={docFile}
            onCapture={setDocFile}
            onClear={() => setDocFile(null)}
          />
          <WebcamCapture
            label="2. Live Face Capture (Recommended)"
            hint="Position the traveler's face inside the frame — we capture a short blink burst"
            facing="user"
            subject="face"
            file={faceFile}
            onCapture={setFaceFile}
            onClear={() => setFaceFile(null)}
            onAllowBurst
          />
        </div>
        <div className="mt-6">
          <IrisCapture file={irisFile} onCapture={setIrisFile} onClear={() => setIrisFile(null)} />
        </div>

        <div className="flex justify-stretch border-t border-slate-700/50 pt-4 sm:justify-end">
          <button
            onClick={handleScan}
            disabled={scanning || !docFile}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-primary to-accent px-6 py-3 font-medium text-white shadow-lg shadow-primary/25 transition-all hover:from-primary/90 hover:to-accent/90 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto sm:px-8"
          >
            {scanning ? (
              <>
                <Loader2 size={20} className="animate-spin" />
                Processing...
              </>
            ) : (
              <>
                <Scan size={20} />
                Initiate Screening
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
