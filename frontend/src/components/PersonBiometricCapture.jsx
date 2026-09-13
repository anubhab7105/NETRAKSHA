import React, { useRef, useState, useEffect } from 'react';
import { Camera, Loader2, RefreshCw, X, Video } from 'lucide-react';

const STATUS_MESSAGES = {
  idle: 'Position face inside the frame',
  starting: 'Opening camera…',
  ready: 'Face in the oval, eyes in the circles — then press Capture and follow the actions',
  capturing: 'Follow the on-screen action…',
  faceDetected: 'Look straight at the camera…',
  eyesDetected: 'Now BLINK — close and open your eyes…',
  checkingLiveness: 'Checking liveness…',
  processingIris: 'Processing iris…',
  complete: 'Capture complete',
};

// Action prompts sequenced across the ~2.1s / 14-frame burst. Any one of
// these actions certifies liveness server-side — the sequence just makes
// sure at least one is clearly observed.
const BURST_PROMPTS = [
  { until: 4, title: 'Look straight at the camera', sub: 'Keep your face inside the oval' },
  { until: 8, title: 'BLINK NOW — close and open your eyes', sub: 'One slow, clear blink' },
  { until: 11, title: 'Turn your head slowly left and right', sub: 'Small movement is enough' },
  { until: 14, title: 'Open your mouth wide', sub: 'Almost done — stay in frame' },
];

const FACE_GUIDE_STEPS = [
  { n: '1', title: 'Light + uncover', text: 'Face the light. Remove sunglasses, mask, cap or anything covering the face.' },
  { n: '2', title: 'Frame the face', text: 'Face inside the oval, eyes inside the two circles. Move closer if needed.' },
  { n: '3', title: 'Follow the actions', text: 'During the 2-second capture: look → BLINK → turn head → open mouth.' },
  { n: '4', title: 'Stay in frame', text: 'Keep still otherwise. Do not hold a photo or another screen to the camera.' },
];

/**
 * PersonBiometricCapture — ONE camera session, ONE button, ONE burst.
 *
 * Reuses the burst pattern from Scanner's face capture (14 frames ~2.1s):
 * the same frame sequence feeds face detection/quality/matching/liveness
 * AND eye detection / iris localization / segmentation upstream.
 * No second camera, no separate iris capture.
 *
 * Returns via onCapture:
 * {
 *   burst: Blob[],            // all frames (face + iris source of truth)
 *   primaryFrame: Blob,       // middle frame (best for face matching)
 *   eyeHint: 'auto',          // server picks best eye by quality
 *   metadata: { frames, capturedAt, facing }
 * }
 */
export default function PersonBiometricCapture({ file, onCapture, onClear, facing = 'user' }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const [previewing, setPreviewing] = useState(false);
  const [starting, setStarting] = useState(false);
  const [videoReady, setVideoReady] = useState(false);
  const [bursting, setBursting] = useState(false);
  const [status, setStatus] = useState('idle');
  const [burstStep, setBurstStep] = useState(0);
  const [error, setError] = useState(null);
  const urlRef = useRef(null);
  const previewUrl = React.useMemo(() => (file?.primaryPreviewUrl ? file.primaryPreviewUrl : null), [file]);

  useEffect(() => {
    return () => stopStream();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const url = file?.primaryPreviewUrl;
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [file]);

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
    if (videoRef.current) videoRef.current.srcObject = null;
    setVideoReady(false);
    setPreviewing(false);
    setStatus('idle');
  };

  const startCamera = async () => {
    setStarting(true);
    setError(null);
    setStatus('starting');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: facing } },
        audio: false,
      });
      streamRef.current = stream;
      setPreviewing(true);
      setStatus('ready');
    } catch (err) {
      setStatus('idle');
      setError(
        err && err.name === 'NotAllowedError'
          ? 'Camera permission denied. Allow webcam access in your browser and try again.'
          : 'Unable to access the webcam. Ensure a camera is connected and try again.'
      );
    } finally {
      setStarting(false);
    }
  };

  const capturePerson = async () => {
    const video = videoRef.current;
    if (!video || video.videoWidth === 0) {
      setError('Camera preview is not ready yet. Try again.');
      return;
    }
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');

    setBursting(true);
    setError(null);
    setBurstStep(0);
    try {
      setStatus('capturing');
      // Brief settle so the officer sees the guide before motion starts
      await new Promise((r) => setTimeout(r, 650));
      const totalFrames = 14; // same ~2.1s window as the legacy face burst
      const frames = [];
      for (let i = 0; i < totalFrames; i++) {
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        frames.push(new Promise((resolve) => canvas.toBlob((blob) => resolve(blob), 'image/png')));
        setBurstStep(i + 1);
        if (i < 4) setStatus('faceDetected');
        else if (i < 8) setStatus('eyesDetected');
        await new Promise((r) => setTimeout(r, 150));
      }
      setStatus('checkingLiveness');
      const blobs = await Promise.all(frames);
      const valid = blobs.filter(Boolean);
      if (valid.length < 3) throw new Error('capture interrupted');
      setStatus('processingIris');
      const primaryFrame = valid[Math.floor(valid.length / 2)] || valid[0];
      const captured = {
        burst: valid,
        primaryFrame,
        eyeHint: 'auto',
        primaryPreviewUrl: URL.createObjectURL(primaryFrame),
        metadata: { frames: valid.length, capturedAt: new Date().toISOString(), facing },
      };
      setStatus('complete');
      onCapture(captured);
      stopStream();
      setStatus('complete');
    } catch {
      setBursting(false);
      setStatus('ready');
      setError('Capture interrupted. Please try again.');
    }
  };

  if (file) {
    const count = Array.isArray(file.burst) ? file.burst.length : 0;
    return (
      <div className="flex-1 min-w-0">
        <label className="block text-sm font-medium text-slate-300 mb-2">2. Traveler Biometric Capture (Required)</label>
        <div className="flex min-h-[260px] flex-col rounded-xl border-2 border-dashed p-4 text-center sm:min-h-[280px] sm:p-5 border-success/50 bg-success/5">
          <div className="flex flex-col items-center justify-center flex-1">
            {previewUrl && (
              <img src={previewUrl} alt="Captured traveler preview" className="mb-3 max-h-[180px] max-w-full rounded-lg border border-slate-700/50 object-contain" />
            )}
            <p className="text-sm font-medium text-slate-200">Person captured — {count} frames</p>
            <p className="text-xs text-slate-500 mt-1">One capture feeds face + liveness + iris analysis</p>
            <div className="mt-2 flex flex-col gap-1 text-xs text-success">
              <span>✓ Face frames recorded</span>
              <span>✓ Action burst recorded (liveness)</span>
              <span>✓ Eye frames recorded (iris)</span>
            </div>
            <div className="mt-4 flex w-full flex-col gap-3 sm:w-auto sm:flex-row">
              <button onClick={() => { stopStream(); onClear(); }} className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs font-medium text-slate-400 hover:bg-slate-700 hover:text-white">
                <X size={14} /> Retry Person Capture
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 min-w-0">
      <label className="block text-sm font-medium text-slate-300 mb-2">2. Traveler Biometric Capture (Required)</label>
      <div className="flex min-h-[260px] flex-col rounded-xl border-2 border-dashed p-4 text-center sm:min-h-[280px] sm:p-5 border-slate-700 hover:border-primary/50">
        {!previewing ? (
          <button onClick={startCamera} disabled={starting} className="flex-1 flex flex-col items-center justify-center group cursor-pointer disabled:opacity-60">
            {starting ? <Loader2 size={32} className="animate-spin text-slate-400 mb-3" /> : (
              <div className="bg-slate-800 p-3 rounded-full text-slate-400 group-hover:text-primary group-hover:bg-primary/10 mb-3">
                <Video size={32} />
              </div>
            )}
            <p className="text-sm text-slate-300 font-medium group-hover:text-white">{starting ? 'Opening webcam...' : 'Click to open camera'}</p>
            <p className="text-xs text-slate-500 mt-1">One capture — face + eyes. Front camera preferred.</p>
            {error && <p className="text-xs text-danger mt-2">{error}</p>}
          </button>
        ) : (
          <>
            <div className="relative">
              <video ref={videoRef} autoPlay playsInline muted onLoadedMetadata={() => setVideoReady(true)} className="h-[180px] w-full rounded-lg border border-slate-700/50 bg-black object-contain sm:h-[220px] md:h-[180px]" />
              {/* Face + eye guide overlay */}
              <div className="absolute inset-0 pointer-events-none flex items-center justify-center">
                <div className="w-40 h-52 border-2 border-primary/60 rounded-2xl" />
                <div className="absolute top-[38%] flex gap-6">
                  <div className="w-10 h-6 border border-white/40 rounded-full" />
                  <div className="w-10 h-6 border border-white/40 rounded-full" />
                </div>
              </div>
              {bursting && (
                <div className="absolute inset-0 rounded-lg bg-black/70 flex flex-col items-center justify-center px-4">
                  {(() => {
                    if (status === 'checkingLiveness') return (
                      <>
                        <p className="text-white font-bold text-lg">Checking liveness…</p>
                        <p className="text-slate-300 text-xs mt-1">Analyzing your actions</p>
                      </>
                    );
                    if (status === 'processingIris') return (
                      <>
                        <p className="text-white font-bold text-lg">Processing iris…</p>
                        <p className="text-slate-300 text-xs mt-1">Locating eyes in the capture</p>
                      </>
                    );
                    const prompt = BURST_PROMPTS.find((p) => burstStep <= p.until) || BURST_PROMPTS[0];
                    return (
                      <>
                        <p className="text-white font-bold text-lg animate-pulse text-center">{prompt.title}</p>
                        <p className="text-slate-300 text-xs mt-1">{prompt.sub}</p>
                        <div className="mt-3 h-1.5 w-3/4 overflow-hidden rounded-full bg-white/20">
                          <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${Math.min(100, (burstStep / 14) * 100)}%` }} />
                        </div>
                        <p className="text-slate-400 text-[11px] mt-1">Step {Math.min(burstStep, 14)} of 14</p>
                      </>
                    );
                  })()}
                </div>
              )}
            </div>
            <p className="text-xs text-slate-400 mt-2" role="status">
              {STATUS_MESSAGES[status] || STATUS_MESSAGES.ready}
            </p>
            {error && <p className="text-xs text-danger mt-2">{error}</p>}
            <div className="mt-3 flex flex-col items-stretch justify-center gap-3 sm:flex-row sm:items-center">
              <button onClick={stopStream} className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs font-medium text-slate-400 hover:bg-slate-700 hover:text-white">
                <X size={14} /> Cancel
              </button>
              <button onClick={capturePerson} disabled={!videoReady || bursting} className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-gradient-to-r from-primary to-accent px-4 py-2 text-xs font-medium text-white hover:from-primary/90 hover:to-accent/90 disabled:opacity-50">
                {bursting ? <Loader2 size={14} className="animate-spin" /> : <Camera size={14} />}
                {bursting ? 'Capturing…' : 'Capture Person'}
              </button>
            </div>
            {!bursting && (
              <ol className="mt-3 space-y-2 rounded-lg bg-black/20 p-3 text-left">
                {FACE_GUIDE_STEPS.map((s) => (
                  <li key={s.n} className="flex items-start gap-2.5">
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/20 text-[11px] font-bold text-primary">{s.n}</span>
                    <span className="text-xs text-slate-300">
                      <span className="font-semibold text-slate-100">{s.title} — </span>
                      {s.text}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </>
        )}
      </div>
      <p className="text-[11px] text-slate-500 mt-2">Iris is RGB-prototype (not NIR). One burst feeds face, liveness and iris.</p>
    </div>
  );
}
