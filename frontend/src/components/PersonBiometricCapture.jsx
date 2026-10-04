import React, { useRef, useState, useEffect } from 'react';
import { Camera, Loader2, RefreshCw, X, Video, CheckCircle2 } from 'lucide-react';

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





const LITE_BURST_FRAMES = 5;
const LITE_FRAME_GAP_MS = 180;
const LITE_MAX_DIM = 640;
const LITE_JPEG_QUALITY = 0.72;




const BURST_PROMPTS = [
  { until: 1, title: 'Look straight at the camera', sub: 'Keep your face inside the oval' },
  { until: 2, title: 'BLINK NOW — close and open your eyes', sub: 'One slow, clear blink' },
  { until: 4, title: 'Turn your head slowly left and right', sub: 'Small movement is enough' },
  { until: 5, title: 'Open your mouth wide', sub: 'Almost done — stay in frame' },
];

function frameToJpeg(video, w, h) {
  // Dedicated canvas per frame: the caller awaits each frame BEFORE drawing
  // the next, so no two toBlob promises share one canvas (which would resolve
  // every frame with the last-drawn pixels).
  return new Promise((resolve) => {
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    canvas.getContext('2d').drawImage(video, 0, 0, w, h);
    canvas.toBlob((blob) => resolve(blob), 'image/jpeg', LITE_JPEG_QUALITY);
  });
}

function scaledDims(video) {
  const vw = video.videoWidth || 640;
  const vh = video.videoHeight || 480;
  const scale = Math.min(1, LITE_MAX_DIM / Math.max(vw, vh));
  return { w: Math.max(2, Math.round(vw * scale)), h: Math.max(2, Math.round(vh * scale)) };
}

const FACE_GUIDE_STEPS = [
  { n: '1', title: 'Light + uncover', text: 'Face the light. Remove sunglasses, mask, cap or anything covering the face.' },
  { n: '2', title: 'Frame the face', text: 'Face inside the oval, eyes inside the two circles. Move closer if needed.' },
  { n: '3', title: 'Follow the actions', text: 'During the ~1-second lite capture: look → BLINK → turn head → open mouth.' },
  { n: '4', title: 'Stay in frame', text: 'Keep still otherwise. Do not hold a photo or another screen to the camera.' },
];

















export default function PersonBiometricCapture({ file, onCapture, onClear, facing = 'user' }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const retakeTimerRef = useRef(null);
  const [previewing, setPreviewing] = useState(false);
  const [starting, setStarting] = useState(false);
  const [videoReady, setVideoReady] = useState(false);
  const [bursting, setBursting] = useState(false);
  const [status, setStatus] = useState('idle');
  const [burstStep, setBurstStep] = useState(0);
  const [error, setError] = useState(null);
  const previewUrl = React.useMemo(() => (file?.primaryPreviewUrl ? file.primaryPreviewUrl : null), [file]);
  const previewUrlRef = useRef(null);

  useEffect(() => {
    // Track the live preview URL; revoke the previous one whenever the
    // capture changes and on unmount. The parent (Scanner) owns the capture
    // object — it must call onClear (which nulls `file`) rather than dropping
    // the reference, so this cleanup always runs.
    if (previewUrlRef.current && previewUrlRef.current !== previewUrl) {
      URL.revokeObjectURL(previewUrlRef.current);
    }
    previewUrlRef.current = previewUrl;
    return () => {
      if (previewUrlRef.current && !previewUrl) {
        // Unmount with no capture — nothing live; handled below.
      }
    };
  }, [previewUrl]);

  useEffect(() => () => {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    }
    if (retakeTimerRef.current) clearTimeout(retakeTimerRef.current);
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
  }, []);

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
    const { w, h } = scaledDims(video);

    setBursting(true);
    setError(null);
    setBurstStep(0);
    try {
      setStatus('capturing');
      // Small settle delay so auto-exposure locks before frame 0.
      await new Promise((r) => setTimeout(r, 650));
      const valid = [];
      for (let i = 0; i < LITE_BURST_FRAMES; i++) {
        // Await each frame sequentially — never push an un-awaited toBlob
        // promise and then redraw the shared canvas.
        const blob = await frameToJpeg(video, w, h);
        if (blob) valid.push(blob);
        setBurstStep(i + 1);
        if (i < 1) setStatus('faceDetected');
        else if (i < 2) setStatus('eyesDetected');
        if (i < LITE_BURST_FRAMES - 1) await new Promise((r) => setTimeout(r, LITE_FRAME_GAP_MS));
      }
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
      setBursting(false);
      setBurstStep(0);
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

  const handleRetake = () => {
    if (retakeTimerRef.current) clearTimeout(retakeTimerRef.current);
    stopStream();
    setBursting(false);
    setBurstStep(0);
    setError(null);
    setStatus('idle');
    onClear();
    retakeTimerRef.current = setTimeout(() => {
      retakeTimerRef.current = null;
      startCamera();
    }, 300);
  };

  if (file) {
    const count = Array.isArray(file.burst) ? file.burst.length : 0;
    return (
      <div className="flex min-w-0 flex-1 flex-col">
        <p className="mb-2 flex items-center gap-2 text-sm font-semibold text-[#172033]">
          <span className="gov-step-dot gov-step-done" aria-hidden="true">✓</span>
          Traveler Biometric Capture
        </p>
        <div className="flex min-h-[260px] flex-col rounded-lg border-2 border-dashed border-[#16803C] bg-[#EAF6EE]/40 p-4 text-center sm:min-h-[280px] sm:p-5">
          <div className="flex flex-1 flex-col items-center justify-center">
            {previewUrl && (
              <img src={previewUrl} alt="Captured traveler preview" className="mb-3 max-h-[180px] max-w-full rounded-lg border border-[#D9DEE7] bg-white object-contain" />
            )}
            <p className="flex items-center gap-1.5 text-sm font-semibold text-[#16803C]">
              <CheckCircle2 size={15} aria-hidden="true" /> Person captured — {count} frames
            </p>
            <p className="mt-1 text-xs text-[#667085]">One capture feeds face + liveness + iris analysis</p>
            <div className="mt-2 flex flex-col gap-1 text-xs font-medium text-[#16803C]">
              <span>✓ Face frames recorded</span>
              <span>✓ Action burst recorded (liveness)</span>
              <span>✓ Eye frames recorded (iris)</span>
            </div>
            <div className="mt-4 flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
              <button type="button" onClick={() => { stopStream(); onClear(); }} className="gov-btn gov-btn-secondary min-h-[36px]! px-3! py-2! text-[13px]!">
                <X size={14} aria-hidden="true" /> Clear
              </button>
              <button type="button" onClick={handleRetake} className="gov-btn gov-btn-secondary min-h-[36px]! px-3! py-2! text-[13px]!">
                <RefreshCw size={14} aria-hidden="true" /> Retake
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <p className="mb-2 flex items-center gap-2 text-sm font-semibold text-[#172033]">
        <span className="gov-step-dot gov-step-current" aria-hidden="true">2</span>
        Traveler Biometric Capture
      </p>
      <div className="flex min-h-[260px] flex-col rounded-lg border-2 border-dashed border-[#BEC6D5] bg-white p-4 text-center transition-colors hover:border-[#1769AA] sm:min-h-[280px] sm:p-5">
        {!previewing ? (
          <button type="button" onClick={startCamera} disabled={starting} className="group flex flex-1 cursor-pointer flex-col items-center justify-center disabled:opacity-60">
            {starting ? <Loader2 size={30} className="mb-3 animate-spin text-[#98A2B3]" aria-hidden="true" /> : (
              <div className="mb-3 rounded-full border border-[#D9DEE7] bg-[#F1F4F9] p-3 text-[#667085] group-hover:border-[#1769AA] group-hover:text-[#1769AA]" aria-hidden="true">
                <Video size={28} />
              </div>
            )}
            <p className="text-sm font-semibold text-[#172033]">{starting ? 'Opening webcam…' : 'Click to open camera'}</p>
            <p className="mt-1 text-xs text-[#667085]">One capture — face + eyes. Front camera preferred.</p>
            {error && <p className="mt-2 text-xs font-medium text-[#C62828]" role="alert">{error}</p>}
          </button>
        ) : (
          <>
            <div className="relative">
              <video ref={videoRef} autoPlay playsInline muted onLoadedMetadata={() => setVideoReady(true)} className="h-[180px] w-full rounded-lg border border-[#D9DEE7] bg-[#172033] object-contain sm:h-[220px] md:h-[180px]" />
              {}
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center" aria-hidden="true">
                <div className="h-52 w-40 rounded-2xl border-2 border-[#1769AA]/70" />
                <div className="absolute top-[38%] flex gap-6">
                  <div className="h-6 w-10 rounded-full border border-white/60" />
                  <div className="h-6 w-10 rounded-full border border-white/60" />
                </div>
              </div>
              {bursting && (
                <div className="absolute inset-0 flex flex-col items-center justify-center rounded-lg bg-[#172033]/80 px-4">
                  {(() => {
                    if (status === 'checkingLiveness') return (
                      <>
                        <p className="text-lg font-bold text-white">Checking liveness…</p>
                        <p className="mt-1 text-xs text-white/75">Analyzing your actions</p>
                      </>
                    );
                    if (status === 'processingIris') return (
                      <>
                        <p className="text-lg font-bold text-white">Processing iris…</p>
                        <p className="mt-1 text-xs text-white/75">Locating eyes in the capture</p>
                      </>
                    );
                    const prompt = BURST_PROMPTS.find((p) => burstStep <= p.until) || BURST_PROMPTS[0];
                    return (
                      <>
                        <p className="animate-pulse text-center text-lg font-bold text-white">{prompt.title}</p>
                        <p className="mt-1 text-xs text-white/75">{prompt.sub}</p>
                        <div className="mt-3 h-1.5 w-3/4 overflow-hidden rounded-full bg-white/25">
                          <div className="h-full rounded-full bg-white transition-all" style={{ width: `${Math.min(100, (burstStep / LITE_BURST_FRAMES) * 100)}%` }} />
                        </div>
                        <p className="mt-1 text-[11px] text-white/70">Step {Math.min(burstStep, LITE_BURST_FRAMES)} of {LITE_BURST_FRAMES} · lite upload for free-tier backend</p>
                      </>
                    );
                  })()}
                </div>
              )}
            </div>
            <p className="mt-2 text-xs text-[#667085]" role="status">
              {STATUS_MESSAGES[status] || STATUS_MESSAGES.ready}
            </p>
            {error && <p className="mt-2 text-xs font-medium text-[#C62828]" role="alert">{error}</p>}
            <div className="mt-3 flex flex-col items-stretch justify-center gap-2 sm:flex-row sm:items-center">
              <button type="button" onClick={stopStream} className="gov-btn gov-btn-secondary min-h-[36px]! px-3! py-2! text-[13px]!">
                <X size={14} aria-hidden="true" /> Cancel
              </button>
              <button type="button" onClick={capturePerson} disabled={!videoReady || bursting} className="gov-btn gov-btn-primary min-h-[36px]! px-4! py-2! text-[13px]!">
                {bursting ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <Camera size={14} aria-hidden="true" />}
                {bursting ? 'Capturing…' : 'Capture Person'}
              </button>
            </div>
            {!bursting && (
              <ol className="mt-3 space-y-2 rounded-lg border border-[#D9DEE7] bg-[#F7F8FA] p-3 text-left">
                {FACE_GUIDE_STEPS.map((s) => (
                  <li key={s.n} className="flex items-start gap-2.5">
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[#E8F1FA] text-[11px] font-bold text-[#123B66]">{s.n}</span>
                    <span className="text-xs text-[#172033]">
                      <span className="font-semibold">{s.title} — </span>
                      <span className="text-[#667085]">{s.text}</span>
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </>
        )}
      </div>
      <p className="mt-2 text-[11px] text-[#98A2B3]">Iris is RGB-prototype (not NIR). One burst feeds face, liveness and iris.</p>
    </div>
  );
}
