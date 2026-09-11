import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Shield, Lock, Loader2, KeyRound, Smartphone } from 'lucide-react';
import api, { apiErrorMessage } from '../api';
import SEO from '../components/SEO';

const inputCls = "w-full bg-black/20 border border-slate-700/50 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-all";
const btnCls = "w-full bg-gradient-to-r from-primary to-accent hover:from-primary/90 hover:to-accent/90 text-white font-medium py-2.5 rounded-lg transition-all shadow-lg shadow-primary/25 flex items-center justify-center gap-2 disabled:opacity-70";

export default function SecuritySetup() {
  const navigate = useNavigate();
  const role = localStorage.getItem('role') || '';
  const needsPassword = localStorage.getItem('must_change_password') === '1';
  const needsMfa = localStorage.getItem('mfa_setup_required') === '1' && role === 'supervisor';

  const [currentPw, setCurrentPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [confirmPw, setConfirmPw] = useState('');
  const [pwMsg, setPwMsg] = useState('');
  const [pwErr, setPwErr] = useState('');
  const [pwLoading, setPwLoading] = useState(false);

  const [mfaKey, setMfaKey] = useState('');
  const [mfaUri, setMfaUri] = useState('');
  const [mfaQr, setMfaQr] = useState('');
  const [mfaServerTime, setMfaServerTime] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [mfaMsg, setMfaMsg] = useState('');
  const [mfaErr, setMfaErr] = useState('');
  const [mfaLoading, setMfaLoading] = useState(false);

  const maybeDone = (pwDone, mfaDone) => {
    const pwOk = !localStorage.getItem('must_change_password') || pwDone;
    const mfaOk = !(localStorage.getItem('mfa_setup_required') === '1') || mfaDone;
    if (pwOk && mfaOk) navigate('/');
  };

  const handlePassword = async (e) => {
    e.preventDefault();
    setPwErr('');
    setPwMsg('');
    if (newPw !== confirmPw) {
      setPwErr('New passwords do not match.');
      return;
    }
    setPwLoading(true);
    try {
      await api.post('/auth/change-password', { current_password: currentPw, new_password: newPw });
      localStorage.removeItem('must_change_password');
      setPwMsg('Password changed.');
      setCurrentPw('');
      setNewPw('');
      setConfirmPw('');
      maybeDone(true, false);
    } catch (err) {
      setPwErr(apiErrorMessage(err, 'Password change failed.'));
    } finally {
      setPwLoading(false);
    }
  };

  const startMfa = async () => {
    setMfaErr('');
    setMfaMsg('');
    setMfaLoading(true);
    try {
      const res = await api.post('/auth/mfa/setup');
      setMfaKey(res.data.manual_key);
      setMfaUri(res.data.otpauth_uri);
      setMfaQr(res.data.qr_data_uri || '');
      setMfaServerTime(res.data.server_time_utc || '');
    } catch (err) {
      setMfaErr(apiErrorMessage(err, 'Could not start MFA enrollment.'));
    } finally {
      setMfaLoading(false);
    }
  };

  const confirmMfa = async (e) => {
    e.preventDefault();
    setMfaErr('');
    setMfaMsg('');
    setMfaLoading(true);
    try {
      await api.post('/auth/mfa/verify', { code: mfaCode });
      localStorage.removeItem('mfa_setup_required');
      setMfaMsg('MFA enabled for your supervisor account.');
      setMfaCode('');
      maybeDone(false, true);
    } catch (err) {
      setMfaErr(apiErrorMessage(err, 'MFA verification failed.'));
    } finally {
      setMfaLoading(false);
    }
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background px-4 py-8">
      <SEO title="Security Setup" description="Rotate your password and enroll supervisor multi-factor authentication." path="/change-password" noindex />
      <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] rounded-full bg-primary/20 blur-[120px] pointer-events-none"></div>

      <div className="glass-panel relative z-10 w-full max-w-md animate-fade-in-up p-6 sm:p-8 space-y-8">
        <div className="flex flex-col items-center">
          <div className="w-14 h-14 bg-gradient-to-br from-primary to-accent rounded-2xl flex items-center justify-center shadow-lg shadow-primary/20 mb-3">
            <Shield size={28} className="text-white" />
          </div>
          <h1 className="text-xl font-bold text-white">Security Setup</h1>
          <p className="text-slate-400 text-sm mt-1 text-center">
            {needsPassword && 'Your password must be rotated before continuing.'}
            {needsPassword && needsMfa && ' '}
            {needsMfa && 'Supervisor accounts require authenticator MFA.'}
            {!needsPassword && !needsMfa && 'Manage your sign-in security below.'}
          </p>
        </div>

        {(needsPassword || !needsMfa) && (
          <form onSubmit={handlePassword} className="space-y-4">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-200 uppercase tracking-wider">
              <KeyRound size={16} /> Change password
            </h2>
            {pwErr && <div className="p-3 bg-danger/10 border border-danger/50 text-danger rounded-lg text-sm text-center">{pwErr}</div>}
            {pwMsg && <div className="p-3 bg-success/10 border border-success/50 text-success rounded-lg text-sm text-center">{pwMsg}</div>}
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1" htmlFor="cp-current">Current password</label>
              <input id="cp-current" type="password" autoComplete="current-password" value={currentPw} onChange={(e) => setCurrentPw(e.target.value)} className={inputCls} required />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1" htmlFor="cp-new">New password</label>
              <input id="cp-new" type="password" autoComplete="new-password" value={newPw} onChange={(e) => setNewPw(e.target.value)} className={inputCls} required />
              <p className="text-xs text-slate-500 mt-1">Min 10 chars, from 3+ of: lowercase, UPPERCASE, digits, symbols. No common words.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1" htmlFor="cp-confirm">Confirm new password</label>
              <input id="cp-confirm" type="password" autoComplete="new-password" value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)} className={inputCls} required />
            </div>
            <button type="submit" disabled={pwLoading} className={btnCls}>
              {pwLoading ? <Loader2 size={20} className="animate-spin" /> : <Lock size={18} />}
              Change password
            </button>
          </form>
        )}

        {role === 'supervisor' && (
          <div className="space-y-4">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-200 uppercase tracking-wider">
              <Smartphone size={16} /> Supervisor MFA
            </h2>
            {mfaErr && <div className="p-3 bg-danger/10 border border-danger/50 text-danger rounded-lg text-sm text-center">{mfaErr}</div>}
            {mfaMsg && <div className="p-3 bg-success/10 border border-success/50 text-success rounded-lg text-sm text-center">{mfaMsg}</div>}
            {!mfaKey ? (
              <>
                <p className="text-sm text-slate-400">
                  Enroll a TOTP authenticator (Google/Microsoft Authenticator, 1Password…). You will receive a manual key to enter.
                </p>
                <button onClick={startMfa} disabled={mfaLoading} className={btnCls}>
                  {mfaLoading ? <Loader2 size={20} className="animate-spin" /> : 'Start MFA enrollment'}
                </button>
              </>
            ) : (
              <form onSubmit={confirmMfa} className="space-y-4">
                <div className="rounded-lg border border-slate-700/50 bg-black/30 p-4">
                  {mfaQr && (
                    <div className="mb-3 flex flex-col items-center">
                      <img src={mfaQr} alt="MFA enrollment QR code — scan with your authenticator app"
                        className="h-44 w-44 rounded-lg border border-slate-700 bg-white p-2" />
                      <p className="text-xs text-slate-400 mt-2 text-center">
                        Scan this with your authenticator app — no typing needed.
                      </p>
                    </div>
                  )}
                  <p className="text-xs text-slate-400 mb-1">Manual key (only if you can't scan):</p>
                  <p className="font-mono text-sm text-white break-all select-all">{mfaKey}</p>
                  <p className="font-mono text-[11px] text-slate-500 break-all select-all mt-2">{mfaUri}</p>
                  {mfaServerTime && (
                    <p className="text-[11px] text-slate-500 mt-2">
                      Server time: {mfaServerTime.replace('T', ' ')}. If your phone's clock differs by more than a minute, turn on automatic date &amp; time — codes won't match otherwise.
                    </p>
                  )}
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-300 mb-1" htmlFor="mfa-code">6-digit code from the app</label>
                  <input id="mfa-code" type="text" inputMode="numeric" autoComplete="one-time-code" value={mfaCode}
                    onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    className={`${inputCls} tracking-[0.5em] text-center`} placeholder="••••••" required />
                </div>
                <button type="submit" disabled={mfaLoading} className={btnCls}>
                  {mfaLoading ? <Loader2 size={20} className="animate-spin" /> : 'Confirm & enable MFA'}
                </button>
              </form>
            )}
          </div>
        )}

        {!needsPassword && !needsMfa && (
          <button onClick={() => navigate('/')} className="w-full text-sm text-slate-400 hover:text-white transition-colors">
            ← Back to dashboard
          </button>
        )}
      </div>
    </div>
  );
}
