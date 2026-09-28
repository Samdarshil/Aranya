import { ArrowRight, Leaf, ServerCog } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { api, getApiBase, setApiBase } from '../api/client';
import { useApp } from '../context/AppContext';
import { ActionButton, apiError, Field, Notice } from '../components/Ui';

export function LoginPage() {
  const { signIn } = useApp();
  const [step, setStep] = useState<'phone' | 'code'>('phone');
  const [phone, setPhone] = useState(''); const [email, setEmail] = useState(''); const [name, setName] = useState(''); const [code, setCode] = useState('');
  const [apiBase, setBase] = useState(getApiBase()); const [debugCode, setDebugCode] = useState(''); const [sent, setSent] = useState('');
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  async function requestCode(event: FormEvent) {
    event.preventDefault(); setError(''); setBusy(true);
    try {
      const result = await api.requestOtp(phone.trim(), email.trim());
      setDebugCode(result.debug_code || '');
      setSent(result.delivered_via?.length ? `Code sent by ${result.delivered_via.join(' and ')}.` : 'Enter the code sent to your phone or email.');
      setStep('code');
    } catch (e) { setError(apiError(e)); } finally { setBusy(false); }
  }
  async function verify(event: FormEvent) {
    event.preventDefault(); setError(''); setBusy(true);
    try { signIn(await api.verifyOtp(phone.trim(), code.trim(), name.trim(), email.trim())); }
    catch (e) { setError(apiError(e)); } finally { setBusy(false); }
  }
  return <main className="login-shell">
    <div className="login-brand"><span className="brand-emblem"><Leaf size={22}/></span><span>ARANYA<span className="brand-period">.</span></span></div>
    <div className="login-grid"><div className="login-story"><div className="eyebrow"><span className="live-dot"/> Agricultural intelligence</div><h1>Every signal.<br/><em>In context.</em></h1><p>Your farm’s history, conditions, and observations—brought together to support the next decision.</p><div className="login-flow"><span>PERCEPTION</span><i/><span>ANALYSIS</span><i/><span>ACTION</span></div></div>
      <section className="login-panel" aria-labelledby="login-title"><div className="eyebrow">Secure sign in</div><h2 id="login-title">Welcome to Aranya</h2><p className="muted">Sign in with a one-time code to continue.</p>
        {error && <Notice tone="error">{error}</Notice>}
        {step === 'phone' ? <form onSubmit={requestCode} className="form-stack"><Field label="Phone number" id="login-phone" type="tel" autoComplete="tel" placeholder="+91 98765 43210" value={phone} onChange={(e) => setPhone(e.target.value)} required/><Field label="Email address" id="login-email" type="email" autoComplete="email" placeholder="Optional backup channel" value={email} onChange={(e) => setEmail(e.target.value)}/><ActionButton type="submit" busy={busy}>Send one-time code <ArrowRight size={16}/></ActionButton></form> : <form onSubmit={verify} className="form-stack"><Notice tone="success">{sent}{debugCode && <><br/>Development code: <strong>{debugCode}</strong></>}</Notice><Field label="Verification code" id="login-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} placeholder="6-digit code" value={code} onChange={(e) => setCode(e.target.value)} required/><Field label="Your name" id="login-name" autoComplete="name" placeholder="Name (first sign in)" value={name} onChange={(e) => setName(e.target.value)}/><ActionButton type="submit" busy={busy}>Verify and continue <ArrowRight size={16}/></ActionButton><button className="text-button" type="button" onClick={() => setStep('phone')}>Use a different number</button></form>}
        <details className="server-settings"><summary><ServerCog size={15}/> Server connection</summary><Field label="API origin" id="api-origin" value={apiBase} onChange={(e) => setBase(e.target.value)} placeholder="http://localhost:8000"/><button className="text-button" onClick={() => { setApiBase(apiBase.trim()); setBase(getApiBase()); }}>Save server address</button><small>Origin only; the app adds the existing API paths.</small></details>
      </section>
    </div><footer className="login-footer"><span>Evidence before certainty.</span><span>Aranya Intelligence · v1</span></footer>
  </main>;
}
