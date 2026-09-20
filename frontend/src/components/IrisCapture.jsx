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
      <div className="gov-card-padded">
        <p className="text-sm font-medium text-[#172033]">Iris ({eye}) captured: {file.name}</p>
        {previewUrl && <img src={previewUrl} alt="iris" className="mt-2 max-h-[120px] rounded-lg border border-[#D9DEE7]" />}
        <button onClick={onClear} className="gov-btn gov-btn-secondary mt-3 !min-h-[34px] !px-3 !py-1.5 !text-xs">Clear</button>
      </div>
    );
  }
  return (
    <div className="gov-card-padded">
      <div className="mb-3 flex items-center gap-2">
        <span className="text-sm font-semibold text-[#172033]">Iris Capture (RGB prototype — not NIR)</span>
        <select value={eye} onChange={e=>setEye(e.target.value)} className="gov-input ml-auto !h-9 !w-auto !text-xs">
          <option value="left">Left eye</option>
          <option value="right">Right eye</option>
        </select>
      </div>
      {!previewing ? (
        <button onClick={startCamera} className="gov-btn gov-btn-secondary w-full">Open Eye Camera</button>
      ) : (
        <div className="space-y-3">
          <div className="relative">
            <video ref={videoRef} autoPlay playsInline muted className="h-[180px] w-full rounded-lg border border-[#D9DEE7] bg-[#172033] object-contain" />
            {}
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center" aria-hidden="true">
              <div className="h-12 w-24 rounded-full border-2 border-[#1769AA]/70" />
              <div className="absolute h-16 w-16 rounded-full border border-white/40" />
            </div>
          </div>
          <p className="text-xs text-[#667085]">Align eye in the oval, good light, no glare. Capture a short burst — multiple frames improve PAD.</p>
          <div className="flex gap-2">
            <button onClick={stopStream} className="gov-btn gov-btn-secondary flex-1 !text-xs">Cancel</button>
            <button onClick={capture} className="gov-btn gov-btn-primary flex-1 !text-xs">Capture Eye</button>
          </div>
        </div>
      )}
      <p className="mt-2 text-[11px] text-[#98A2B3]">RGB iris is prototype/research; NIR hardware (850nm) is the production path. See docs/iris_architecture.md</p>
    </div>
  );
}
