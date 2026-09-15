import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ShieldCheck, Lock, UserRound, Loader2, AlertTriangle } from 'lucide-react';
import api, { apiErrorMessage } from '../api';
import SEO from '../components/SEO';

export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [mfaToken, setMfaToken] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const storeSession = (data) => {
    localStorage.setItem('token', data.token);
    localStorage.setItem('role', data.role);
    localStorage.setItem('username', data.username);
    if (data.must_change_password) localStorage.setItem('must_change_password', '1');
    else localStorage.removeItem('must_change_password');
    if (data.mfa_setup_required) localStorage.setItem('mfa_setup_required', '1');
    else localStorage.removeItem('mfa_setup_required');
    if (data.must_change_password || data.mfa_setup_required) navigate('/change-password');
    else navigate('/');
  };

  const handleLogin = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await api.post('/auth/login', { username, password });
      if (res.data.mfa_required) {
        // Supervisor second factor — stay here and prompt for the code.
        setMfaToken(res.data.mfa_token);
        if (res.data.must_change_password) localStorage.setItem('must_change_password', '1');
      } else {
        storeSession(res.data);
      }
    } catch (err) {
      const status = err.response?.status;
      setError(status === 429
        ? (err.response?.data?.detail || 'Too many attempts. Please wait and retry.')
        : apiErrorMessage(err, 'Login failed. Please check credentials.'));
    } finally {
      setLoading(false);
    }
  };

  const handleMfa = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await api.post('/auth/mfa/challenge', { mfa_token: mfaToken, code: mfaCode });
      setMfaToken('');
      setMfaCode('');
      storeSession(res.data);
    } catch (err) {
      setError(apiErrorMessage(err, 'MFA verification failed.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen bg-[#F7F8FA]">
      <SEO
        title="Officer Login"
        description="Secure sign-in for authorized Sashastra Seema Bal officers to the Netraksha identity document screening portal."
        path="/login"
      />
      {/* Left — official identity panel (desktop) */}
      <div className="hidden w-[44%] shrink-0 flex-col justify-between bg-[#123B66] p-10 text-white lg:flex">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-white/70">
            Government of India · Ministry of Home Affairs
          </p>
          <div className="mt-6 flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-white/10" aria-hidden="true">
              <ShieldCheck size={28} />
            </div>
            <div>
              <p className="text-2xl font-bold tracking-tight">NETRAKSHA</p>
              <p className="text-sm text-white/75">AI-Based Identity Verification</p>
            </div>
          </div>
          <div className="mt-8 h-px w-16 bg-[#F59E0B]" aria-hidden="true" />
          <ul className="mt-8 space-y-4 text-sm text-white/85">
            <li className="flex gap-3"><span aria-hidden="true">—</span> Document authenticity, MRZ and registry verification in one workstation.</li>
            <li className="flex gap-3"><span aria-hidden="true">—</span> Face comparison, liveness and fraud detection with explainable verdicts.</li>
            <li className="flex gap-3"><span aria-hidden="true">—</span> Every check and officer decision written to an immutable audit trail.</li>
          </ul>
        </div>
        <p className="text-xs text-white/60">
          Official use only · Sashastra Seema Bal · Unauthorised access is prohibited and logged.
        </p>
      </div>

      {/* Right — sign-in form */}
      <div className="flex min-w-0 flex-1 items-center justify-center px-4 py-10">
        <div className="w-full max-w-[420px]">
          <div className="mb-6 flex items-center gap-3 lg:hidden">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#123B66] text-white" aria-hidden="true">
              <ShieldCheck size={22} />
            </div>
            <div className="leading-tight">
              <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[#667085]">Government of India</p>
              <p className="text-lg font-bold text-[#123B66]">NETRAKSHA</p>
            </div>
          </div>

          <div className="gov-card-padded">
            <h1 className="text-xl font-bold text-[#172033]">Officer Sign In</h1>
            <p className="gov-subtitle">Authorised personnel only. Sessions and attempts are audited.</p>

            {error && (
              <div className="gov-notice gov-notice-red mt-4" role="alert">
                <AlertTriangle size={18} className="shrink-0" aria-hidden="true" />
                <span>{error}</span>
              </div>
            )}

            <form onSubmit={mfaToken ? handleMfa : handleLogin} className="mt-5 space-y-4">
              {!mfaToken ? (
                <>
                  <div>
                    <label htmlFor="login-username" className="gov-label">Username</label>
                    <div className="relative">
                      <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-[#98A2B3]" aria-hidden="true">
                        <UserRound size={17} />
                      </span>
                      <input
                        id="login-username"
                        type="text"
                        autoComplete="username"
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                        className="gov-input gov-input-with-icon"
                        required
                      />
                    </div>
                  </div>
                  <div>
                    <label htmlFor="login-password" className="gov-label">Password</label>
                    <div className="relative">
                      <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-[#98A2B3]" aria-hidden="true">
                        <Lock size={17} />
                      </span>
                      <input
                        id="login-password"
                        type="password"
                        autoComplete="current-password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        className="gov-input gov-input-with-icon"
                        required
                      />
                    </div>
                    <p className="gov-help">Use your issued workstation credentials. Contact your supervisor if locked out.</p>
                  </div>
                </>
              ) : (
                <div>
                  <p className="mb-3 text-sm text-[#172033]">
                    Supervisor sign-in needs a second step — enter the 6-digit code from your authenticator app.
                  </p>
                  <label htmlFor="login-mfa" className="gov-label">Authenticator code</label>
                  <div className="relative">
                    <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-[#98A2B3]" aria-hidden="true">
                      <Lock size={17} />
                    </span>
                    <input
                      id="login-mfa"
                      type="text"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      value={mfaCode}
                      onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                      className="gov-input gov-input-with-icon text-center tracking-[0.5em]"
                      placeholder="••••••"
                      required
                    />
                  </div>
                  <button type="button" onClick={() => { setMfaToken(''); setMfaCode(''); setError(''); }}
                    className="gov-btn gov-btn-ghost mt-2 w-full !justify-center">
                    ← Back to username / password
                  </button>
                </div>
              )}

              <button type="submit" disabled={loading} className="gov-btn gov-btn-primary w-full">
                {loading ? <Loader2 size={18} className="animate-spin" aria-hidden="true" /> : (mfaToken ? 'Verify Code' : 'Sign In Securely')}
              </button>
            </form>
          </div>
          <p className="mt-4 text-center text-xs text-[#98A2B3]">
            Protected workstation · All sign-in events are recorded for audit.
          </p>
        </div>
      </div>
    </div>
  );
}
