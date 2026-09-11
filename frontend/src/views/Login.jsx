import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Shield, Lock, User, Loader2 } from 'lucide-react';
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
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background px-4 py-8">
      <SEO
        title="Officer Login"
        description="Secure sign-in for authorized Sashastra Seema Bal officers to the Netraksha identity document screening portal."
        path="/login"
      />
      {/* Background blobs */}
      <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] rounded-full bg-primary/20 blur-[120px] pointer-events-none"></div>
      <div className="absolute bottom-[-20%] right-[-10%] w-[50%] h-[50%] rounded-full bg-accent/20 blur-[120px] pointer-events-none"></div>
      
      <div className="glass-panel relative z-10 w-full max-w-md animate-fade-in-up p-6 sm:p-8">
        <div className="flex flex-col items-center mb-8">
          <div className="w-16 h-16 bg-gradient-to-br from-primary to-accent rounded-2xl flex items-center justify-center shadow-lg shadow-primary/20 mb-4">
            <Shield size={32} className="text-white" />
          </div>
<h1 className="text-2xl font-bold text-white">Netraksha</h1>
           <p className="text-slate-400 text-sm mt-1">See. Verify. Secure.</p>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-danger/10 border border-danger/50 text-danger rounded-lg text-sm text-center">
            {error}
          </div>
        )}

        <form onSubmit={mfaToken ? handleMfa : handleLogin} className="space-y-4">
          {!mfaToken ? (
          <>
          <div>
            <label htmlFor="login-username" className="block text-sm font-medium text-slate-300 mb-1">Username</label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-500">
                <User size={18} />
              </div>
              <input
                id="login-username"
                type="text"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full bg-black/20 border border-slate-700/50 rounded-lg pl-10 pr-4 py-2.5 text-white focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-all"
                required
              />
            </div>
          </div>

          <div>
            <label htmlFor="login-password" className="block text-sm font-medium text-slate-300 mb-1">Password</label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-500">
                <Lock size={18} />
              </div>
              <input
                id="login-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-black/20 border border-slate-700/50 rounded-lg pl-10 pr-4 py-2.5 text-white focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-all"
                required
              />
            </div>
          </div>
          </>
          ) : (
          <div>
            <p className="text-sm text-slate-300 mb-3 text-center">
              Supervisor sign-in needs a second step — enter the 6-digit code from your authenticator app.
            </p>
            <label htmlFor="login-mfa" className="block text-sm font-medium text-slate-300 mb-1">Authenticator code</label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-500">
                <Lock size={18} />
              </div>
              <input
                id="login-mfa"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                className="w-full bg-black/20 border border-slate-700/50 rounded-lg pl-10 pr-4 py-2.5 text-white tracking-[0.5em] text-center focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-all"
                placeholder="••••••"
                required
              />
            </div>
            <button type="button" onClick={() => { setMfaToken(''); setMfaCode(''); setError(''); }}
              className="mt-3 w-full text-xs text-slate-400 hover:text-white transition-colors">
              ← Back to username / password
            </button>
          </div>
          )}

          <button 
            type="submit" 
            disabled={loading}
            className="w-full bg-gradient-to-r from-primary to-accent hover:from-primary/90 hover:to-accent/90 text-white font-medium py-2.5 rounded-lg transition-all shadow-lg shadow-primary/25 flex items-center justify-center gap-2 mt-6 disabled:opacity-70"
          >
            {loading ? <Loader2 size={20} className="animate-spin" /> : (mfaToken ? 'Verify Code' : 'Sign In')}
          </button>
        </form>
      </div>
    </div>
  );
}
