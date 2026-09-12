import React, { useRef, useState, useEffect } from 'react';

export default function IrisCapture({ onCapture, onClear, file }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const [previewing, setPreviewing] = useState(false);
  const [eye, setEye] = useState('left');
  const previewUrl = file ? URL.createObjectURL(file) : null;

  const startCamera = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'user' } }, audio: false });
      streamRef.current = stream;
      setPreviewing(true);
      setTimeout(() => {
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.play().catch(()=>{});
        }
      }, 100);
    } catch (e) {
      alert('Camera permission denied or not available: ' + e.message);
    }
  };
  const stopStream = () => {
    if (streamRef.current) streamRef.current.getTracks().forEach(t=>t.stop());
    setPreviewing(false);
  };
  const capture = () => {
    const video = videoRef.current;
    if (!video || video.videoWidth===0) return;
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth; canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video,0,0);
    canvas.toBlob(blob=>{
      if (!blob) return;
      const f = new File([blob], `iris_${eye}.png`, {type:'image/png'});
      f.eye = eye;
      onCapture(f);
      stopStream();
    }, 'image/png');
  };
  useEffect(()=>()=>stopStream(),[]);

  if (file) {
    return (
      <div className="glass-panel p-4">
        <p className="text-sm text-slate-200">Iris ({eye}) captured: {file.name}</p>
        {previewUrl && <img src={previewUrl} alt="iris" className="mt-2 max-h-[120px] rounded border border-slate-700" />}
        <button onClick={onClear} className="mt-3 text-xs px-3 py-1 bg-slate-800 border border-slate-700 rounded text-slate-300">Clear</button>
      </div>
    );
  }
  return (
    <div className="glass-panel p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-sm font-medium text-slate-300">Iris Capture (RGB prototype — not NIR)</span>
        <select value={eye} onChange={e=>setEye(e.target.value)} className="ml-auto bg-black/30 border border-slate-700 rounded px-2 py-1 text-xs text-white">
          <option value="left">Left eye</option>
          <option value="right">Right eye</option>
        </select>
      </div>
      {!previewing ? (
        <button onClick={startCamera} className="w-full py-2 bg-primary/20 hover:bg-primary/30 text-primary border border-primary/30 rounded-lg text-sm">Open Eye Camera</button>
      ) : (
        <div className="space-y-3">
          <div className="relative">
            <video ref={videoRef} autoPlay playsInline muted className="w-full h-[180px] bg-black rounded-lg object-contain border border-slate-700" />
            {/* Eye guide overlay */}
            <div className="absolute inset-0 pointer-events-none flex items-center justify-center">
              <div className="w-24 h-12 border-2 border-primary/60 rounded-full" />
              <div className="absolute w-16 h-16 border border-white/20 rounded-full" />
            </div>
          </div>
          <p className="text-xs text-slate-400">Align eye in the oval, good light, no glare. Capture a short burst — multiple frames improve PAD.</p>
          <div className="flex gap-2">
            <button onClick={stopStream} className="flex-1 py-2 bg-slate-800 border border-slate-700 rounded text-xs text-slate-300">Cancel</button>
            <button onClick={capture} className="flex-1 py-2 bg-primary text-white rounded text-xs font-medium">Capture Eye</button>
          </div>
        </div>
      )}
      <p className="text-[11px] text-slate-500 mt-2">RGB iris is prototype/research; NIR hardware (850nm) is the production path. See docs/iris_architecture.md</p>
    </div>
  );
}
