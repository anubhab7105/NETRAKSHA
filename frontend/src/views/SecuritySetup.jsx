import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ShieldCheck, Lock, Loader2, KeyRound, Smartphone, AlertTriangle, CheckCircle2, LogOut } from 'lucide-react';
import api, { apiErrorMessage } from '../api';
import SEO from '../components/SEO';

const KNOWN_SESSION_KEYS = ['token', 'role', 'username', 'must_change_password', 'mfa_setup_required'];

function clearSession() {
  KNOWN_SESSION_KEYS.forEach((k) => localStorage.removeItem(k));
}

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
      // Clear enrollment material on success so the key/QR never linger in state.
      setMfaKey('');
      setMfaUri('');
      setMfaQr('');
      setMfaServerTime('');
      setMfaCode('');
      maybeDone(false, true);
    } catch (err) {
      setMfaErr(apiErrorMessage(err, 'MFA verification failed.'));
    } finally {
      setMfaLoading(false);
    }
  };

  const handleSignOut = async () => {
    try {
      await api.post('/auth/logout');
    } catch {
      // Still wipe local session even if the server call fails.
    }
    clearSession();
    navigate('/login');
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#F7F8FA] px-4 py-10">
      <SEO title="Security Setup" description="Rotate your password and enroll supervisor multi-factor authentication." path="/change-password" noindex />
      <div className="w-full max-w-[560px]">
        <div className="mb-4 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#123B66] text-white" aria-hidden="true">
            <ShieldCheck size={22} />
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[#667085]">Government of India · NETRAKSHA</p>
            <h1 className="text-xl font-bold text-[#172033]">Security Setup</h1>
          </div>
        </div>

        <div className="gov-card-padded space-y-6">
          <p className="text-sm text-[#667085]">
            {needsPassword && 'Your password must be rotated before continuing.'}
            {needsPassword && needsMfa && ' '}
            {needsMfa && 'Supervisor accounts require authenticator MFA.'}
            {!needsPassword && !needsMfa && 'Manage your sign-in security below.'}
          </p>

          {(needsPassword || !needsMfa) && (
            <form onSubmit={handlePassword} className="space-y-4 border-t border-[#D9DEE7] pt-5">
              <h2 className="flex items-center gap-2 text-[13px] font-bold uppercase tracking-[0.06em] text-[#123B66]">
                <KeyRound size={16} aria-hidden="true" /> Change password
              </h2>
              {pwErr && <div className="gov-notice gov-notice-red" role="alert"><AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />{pwErr}</div>}
              {pwMsg && <div className="gov-notice gov-notice-green" role="status"><CheckCircle2 size={16} className="mt-0.5 shrink-0" aria-hidden="true" />{pwMsg}</div>}
              <div>
                <label className="gov-label" htmlFor="cp-current">Current password</label>
                <input id="cp-current" type="password" autoComplete="current-password" value={currentPw} onChange={(e) => setCurrentPw(e.target.value)} className="gov-input" required />
              </div>
              <div>
                <label className="gov-label" htmlFor="cp-new">New password</label>
                <input id="cp-new" type="password" autoComplete="new-password" value={newPw} onChange={(e) => setNewPw(e.target.value)} className="gov-input" required />
                <p className="gov-help">Min 10 chars, from 3+ of: lowercase, UPPERCASE, digits, symbols. No common words.</p>
              </div>
              <div>
                <label className="gov-label" htmlFor="cp-confirm">Confirm new password</label>
                <input id="cp-confirm" type="password" autoComplete="new-password" value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)} className="gov-input" required />
              </div>
              <button type="submit" disabled={pwLoading} className="gov-btn gov-btn-primary w-full">
                {pwLoading ? <Loader2 size={18} className="animate-spin" aria-hidden="true" /> : <Lock size={17} aria-hidden="true" />}
                Change password
              </button>
            </form>
          )}

          {role === 'supervisor' && (
            <div className="space-y-4 border-t border-[#D9DEE7] pt-5">
              <h2 className="flex items-center gap-2 text-[13px] font-bold uppercase tracking-[0.06em] text-[#123B66]">
                <Smartphone size={16} aria-hidden="true" /> Supervisor MFA
              </h2>
              {mfaErr && <div className="gov-notice gov-notice-red" role="alert"><AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />{mfaErr}</div>}
              {mfaMsg && <div className="gov-notice gov-notice-green" role="status"><CheckCircle2 size={16} className="mt-0.5 shrink-0" aria-hidden="true" />{mfaMsg}</div>}
              {!mfaKey ? (
                <>
                  <p className="text-sm text-[#667085]">
                    Enroll a TOTP authenticator (Google/Microsoft Authenticator, 1Password…). You will receive a manual key to enter.
                  </p>
                  <button onClick={startMfa} disabled={mfaLoading} className="gov-btn gov-btn-primary w-full">
                    {mfaLoading ? <Loader2 size={18} className="animate-spin" aria-hidden="true" /> : 'Start MFA enrollment'}
                  </button>
                </>
              ) : (
                <form onSubmit={confirmMfa} className="space-y-4">
                  <div className="rounded-lg border border-[#D9DEE7] bg-[#F7F8FA] p-4">
                    {mfaQr && (
                      <div className="mb-3 flex flex-col items-center">
                        <img src={mfaQr} alt="MFA enrollment QR code — scan with your authenticator app"
                          className="h-44 w-44 rounded-lg border border-[#D9DEE7] bg-white p-2" />
                        <p className="gov-help mt-2 text-center">
                          Scan this with your authenticator app — no typing needed.
                        </p>
                      </div>
                    )}
                    <p className="text-xs font-semibold text-[#667085]">Manual key (only if you can't scan):</p>
                    <p className="break-all font-mono text-sm text-[#172033] select-all">{mfaKey}</p>
                    <p className="mt-2 break-all font-mono text-[11px] text-[#98A2B3] select-all">{mfaUri}</p>
                    {mfaServerTime && (
                      <p className="mt-2 text-[11px] text-[#667085]">
                        Server time: {mfaServerTime.replace('T', ' ')}. If your phone's clock differs by more than a minute, turn on automatic date &amp; time — codes won't match otherwise.
                      </p>
                    )}
                  </div>
                  <div>
                    <label className="gov-label" htmlFor="mfa-code">6-digit code from the app</label>
                    <input id="mfa-code" type="text" inputMode="numeric" autoComplete="one-time-code" value={mfaCode}
                      onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                      className="gov-input text-center tracking-[0.5em]" placeholder="••••••" required />
                  </div>
                  <button type="submit" disabled={mfaLoading} className="gov-btn gov-btn-primary w-full">
                    {mfaLoading ? <Loader2 size={18} className="animate-spin" aria-hidden="true" /> : 'Confirm & enable MFA'}
                  </button>
                  <button type="button" onClick={() => { setMfaCode(''); setMfaErr(''); startMfa(); }}
                    disabled={mfaLoading}
                    className="gov-btn gov-btn-ghost w-full justify-center! disabled:opacity-60">
                    Codes never match? Discard this QR and get a fresh one — then scan only the new code.
                  </button>
                </form>
              )}
            </div>
          )}

          {!needsPassword && !needsMfa && (
            <button onClick={() => navigate('/')} className="gov-btn gov-btn-ghost w-full justify-center">
              ← Back to dashboard
            </button>
          )}
          <button onClick={handleSignOut} aria-label="Sign out" className="gov-btn gov-btn-ghost w-full justify-center">
            <LogOut size={16} aria-hidden="true" /> Sign Out
          </button>
        </div>
      </div>
    </div>
  );
}
