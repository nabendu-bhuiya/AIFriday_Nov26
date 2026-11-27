import { useEffect, useState } from 'react'
import { api, setToken } from './api'

export const Logo = ({ size = 32 }) => (
  <svg width={size} height={size} viewBox="0 0 36 36" aria-hidden="true"><rect x="2" y="2" width="32" height="32" rx="8" fill="none" stroke="#9CCBF2" strokeWidth="2.5" /><path d="M10 18h5l3-7 4 14 3-7h3" fill="none" stroke="#9CCBF2" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
)

export default function Login({ onLogin }) {
  const [email, setEmail] = useState('')
  const [pwd, setPwd] = useState('')
  const [role, setRole] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    const e = email.trim()
    if (!e) { setRole(null); return }
    const t = setTimeout(() => api(`/roles/lookup?email=${encodeURIComponent(e)}`).then(setRole).catch(() => setRole({ found: false })), 200)
    return () => clearTimeout(t)
  }, [email])

  const submit = async (ev) => {
    ev.preventDefault()
    try {
      const r = await api('/login', { method: 'POST', body: { email, password: pwd } })
      setToken(r.token); onLogin(r.user)
    } catch (e) { setErr(e.message) }
  }

  return (
    <div className="login">
      <section className="hero">
        <div className="brand"><Logo />TrialLens</div>
        <h1>Every answer cited.<br />Every inconsistency caught.</h1>
        <p>An agentic assistant that summarizes clinical trial documents, answers questions with source citations and checks protocols, consent forms, brochures and submissions against each other.</p>
        {[['S', 'Summaries tailored to each role', 'Executive summary plus a lens per role. Every claim links to its page and is checked by a separate verifier.'],
          ['C', 'Cross-document consistency agent', 'Compares Protocol, Amendments, ICF, IB, SAP and the regulatory submission on visits, eligibility, dosing, risks and endpoints.'],
          ['G', 'Governed by design', 'PHI redaction before the LLM, role-based retrieval, GxP e-signature, hash-chained audit trail and full agent tracing.']].map(([i, b, s]) => (
          <div className="feat" key={b}><i>{i}</i><div><b>{b}</b><span>{s}</span></div></div>
        ))}
        <div style={{ marginTop: 'auto', fontSize: 13, color: '#C3D6EA' }}>Proof of concept · synthetic, de-identified trial data only</div>
      </section>
      <section className="panel">
        <form className="card-login" onSubmit={submit}>
          <div><h2 style={{ fontSize: 22, marginBottom: 6 }}>Sign in</h2><div className="muted" style={{ fontSize: 14 }}>Use your work email. Your role is detected from your account.</div></div>
          <label className="field">Work email<input type="email" autoComplete="username" value={email} onChange={(e) => { setEmail(e.target.value); setErr('') }} /></label>
          <label className="field">Password<input type="password" autoComplete="current-password" value={pwd} onChange={(e) => { setPwd(e.target.value); setErr('') }} /></label>
          <div role="status" className={`rolebox ${role?.found ? 'ok' : ''}`}>
            <span className="small muted">Role</span>
            <span style={{ fontSize: 15, fontWeight: 600 }}>{role?.found ? role.role_name : email ? 'No role found' : 'Enter your email'}</span>
            <span style={{ fontSize: 13 }} className="muted">{role?.found ? role.lens.split(':')[0] || 'Platform administration' : email ? 'This email has no TrialLens role. Contact your administrator.' : 'Your role appears here automatically.'}</span>
          </div>
          {err && <div className="err">{err}</div>}
          <button className="btn" type="submit" disabled={!role?.found || !pwd}>Sign in</button>
        </form>
      </section>
    </div>
  )
}
