import React, { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { UploadCloud, Camera, Loader2, FileCheck2 } from 'lucide-react';
import api from '../api';

export default function Scanner() {
  const [docFile, setDocFile] = useState(null);
  const [faceFile, setFaceFile] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  const handleScan = async () => {
    if (!docFile) {
      setError("Please upload a document image.");
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
      const detail = err.response?.data?.detail || err.response?.data?.message;
      const status = err.response?.status;
      setError(
        detail
          ? `Screening failed (${status || 'error'}): ${detail}`
          : "Screening failed. Please ensure the backend is running and try again."
      );
      setScanning(false);
    }
  };

  const FileUploader = ({ label, icon, file, setFile, accept }) => (
    <div className="flex-1">
      <label className="block text-sm font-medium text-slate-300 mb-2">{label}</label>
      <div 
        className={`border-2 border-dashed rounded-xl p-8 text-center transition-all cursor-pointer hover:bg-white/5 flex flex-col items-center justify-center min-h-[200px]
          ${file ? 'border-success/50 bg-success/5' : 'border-slate-700 hover:border-primary/50'}`}
      >
        <input 
          type="file" 
          className="hidden" 
          accept={accept}
          onChange={(e) => {
            if(e.target.files && e.target.files.length > 0) {
              setFile(e.target.files[0]);
            }
          }}
        />
        {file ? (
          <>
            <div className="bg-success/20 p-3 rounded-full text-success mb-3">
              <FileCheck2 size={32} />
            </div>
            <p className="text-sm text-slate-200 font-medium truncate max-w-[200px]">{file.name}</p>
            <p className="text-xs text-slate-500 mt-1">{(file.size / 1024).toFixed(1)} KB</p>
          </>
        ) : (
          <>
            <div className="bg-slate-800 p-3 rounded-full text-slate-400 mb-3">
              {icon}
            </div>
            <p className="text-sm text-slate-300 font-medium">Click to browse</p>
            <p className="text-xs text-slate-500 mt-1">PNG, JPG up to 10MB</p>
          </>
        )}
      </div>
    </div>
  );

  return (
    <div className="space-y-6 animate-fade-in max-w-4xl mx-auto">
      <header>
        <h2 className="text-2xl font-bold text-white">Kiosk Simulator</h2>
        <p className="text-slate-400 text-sm mt-1">Upload a document and live capture to initiate the AI screening pipeline.</p>
      </header>

      {error && (
        <div className="p-4 bg-danger/10 border border-danger/50 text-danger rounded-lg">
          {error}
        </div>
      )}

      <div className="glass-panel p-6">
        <div className="flex gap-6 mb-8">
          <label className="block flex-1">
            <FileUploader 
              label="1. Document Image (Required)" 
              icon={<UploadCloud size={32} />} 
              file={docFile} 
              setFile={setDocFile} 
              accept="image/*" 
            />
          </label>
          <label className="block flex-1">
            <FileUploader 
              label="2. Live Capture (Optional)" 
              icon={<Camera size={32} />} 
              file={faceFile} 
              setFile={setFaceFile} 
              accept="image/*" 
            />
          </label>
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

// Ensure Scan icon is available
import { Scan } from 'lucide-react';
