import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Camera, Loader2, Scan, RefreshCw, X, Video, Image as ImageIcon } from 'lucide-react';
import api from '../api';

function WebcamCapture({ label, hint, facing, subject, file, onCapture, onClear }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const [previewing, setPreviewing] = useState(false);
  const [starting, setStarting] = useState(false);
  const [videoReady, setVideoReady] = useState(false);
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

  const capturePhoto = () => {
    const video = videoRef.current;
    if (!video || video.videoWidth === 0) {
      setError('Camera preview is not ready yet. Try again.');
      return;
    }
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      if (!blob) return;
      const captured = new File([blob], `${subject === 'document' ? 'document_capture' : 'live_capture'}.png`, { type: 'image/png' });
      onCapture(captured);
      stopStream();
    }, 'image/png');
  };

  return (
    <div className="flex-1">
      <label className="block text-sm font-medium text-slate-300 mb-2">{label}</label>
      <div className={`border-2 border-dashed rounded-xl p-5 text-center transition-all min-h-[280px] flex flex-col ${file ? 'border-success/50 bg-success/5' : 'border-slate-700 hover:border-primary/50'}`}>
        {file ? (
          <div className="flex flex-col items-center justify-center flex-1">
            {previewUrl && (
              <img src={previewUrl} alt={label} className="max-h-[180px] object-contain rounded-lg mb-3 border border-slate-700/50" />
            )}
            <p className="text-sm text-slate-200 font-medium truncate max-w-[200px]">{file.name}</p>
            <p className="text-xs text-slate-500 mt-1">{(file.size / 1024).toFixed(1)} KB</p>
            <div className="flex gap-3 mt-4">
              <button
                onClick={() => { stopStream(); onClear(); }}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg px-3 py-2 transition-all"
              >
                <X size={14} />
                Clear
              </button>
              <button
                onClick={startCamera}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-primary bg-primary/10 hover:bg-primary/20 border border-primary/40 rounded-lg px-3 py-2 transition-all"
              >
                <RefreshCw size={14} />
                Retake
              </button>
            </div>
          </div>
        ) : previewing ? (
          <>
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              onLoadedMetadata={() => setVideoReady(true)}
              className="w-full h-[180px] object-contain bg-black rounded-lg border border-slate-700/50"
            />
            <p className="text-xs text-slate-400 mt-2">{hint}</p>
            {error && <p className="text-xs text-danger mt-2">{error}</p>}
            <div className="flex items-center justify-center gap-3 mt-3">
              <button
                onClick={stopStream}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg px-3 py-2 transition-all"
              >
                <X size={14} />
                Cancel
              </button>
              <button
                onClick={capturePhoto}
                disabled={!videoReady}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-white bg-gradient-to-r from-primary to-accent hover:from-primary/90 hover:to-accent/90 rounded-lg px-4 py-2 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Camera size={14} />
                Capture Photo
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

export default function Scanner() {
  const [docFile, setDocFile] = useState(null);
  const [faceFile, setFaceFile] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  const handleScan = async () => {
    if (!docFile) {
      setError("Please capture a document image using the webcam.");
      return;
    }

    setScanning(true);
    setError(null);

    const formData = new FormData();
    formData.append('document_image', docFile);
    if (faceFile) {
      formData.append('live_capture', faceFile);
    }

    try {
      const res = await api.post('/screen', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      navigate(`/case/${res.data.case_id}`);
    } catch (err) {
      console.error(err);
      const detail =
        err.response?.data?.detail ||
        (typeof err.response?.data === 'string' ? err.response.data : null);
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
    <div className="space-y-6 animate-fade-in max-w-4xl mx-auto">
      <header>
        <h2 className="text-2xl font-bold text-white">Kiosk Simulator</h2>
        <p className="text-slate-400 text-sm mt-1">Use the webcams to capture the identity document and the traveler's live face.</p>
      </header>

      {error && (
        <div className="p-4 bg-danger/10 border border-danger/50 text-danger rounded-lg">
          {error}
        </div>
      )}

      <div className="glass-panel p-6">
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
            hint="Position the traveler's face inside the frame"
            facing="user"
            subject="face"
            file={faceFile}
            onCapture={setFaceFile}
            onClear={() => setFaceFile(null)}
          />
        </div>

        <div className="flex justify-end pt-4 border-t border-slate-700/50">
          <button
            onClick={handleScan}
            disabled={scanning || !docFile}
            className="bg-gradient-to-r from-primary to-accent hover:from-primary/90 hover:to-accent/90 text-white font-medium px-8 py-3 rounded-lg transition-all shadow-lg shadow-primary/25 flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {scanning ? (
              <>
                <Loader2 size={20} className="animate-spin" />
                Processing (Avg: 1.5s)...
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