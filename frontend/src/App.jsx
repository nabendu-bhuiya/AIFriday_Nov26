import { useEffect, useState } from 'react'
import { api, hasToken, setToken } from './api'
import Login, { Logo } from './Login'
import AskPanel from './AskPanel'
import Dashboard from './pages/Dashboard'
import Documents from './pages/Documents'
import Discrepancies from './pages/Discrepancies'
import DocAuditLog from './pages/DocAuditLog'
import Ingestion from './pages/Ingestion'
import SignOff from './pages/SignOff'
import AuditTrail from './pages/AuditTrail'
import AdminConsole from './pages/AdminConsole'

const NAV = {
  com: [['dash', 'Dashboard'], ['docs', 'Documents & summaries'], ['disc', 'Discrepancies'], ['ver', 'Doc Audit Log'], ['ingest', 'Ingestion']],
  cra: [['dash', 'Dashboard'], ['docs', 'Documents & summaries'], ['disc', 'Discrepancies'], ['ver', 'Doc Audit Log']],
  mr: [['dash', 'Dashboard'], ['docs', 'Documents & summaries'], ['disc', 'Discrepancies'], ['ver', 'Doc Audit Log']],
  aud: [['dash', 'Dashboard'], ['signoff', 'GxP sign-off'], ['docs', 'Documents & summaries'], ['disc', 'Discrepancies'], ['ver', 'Doc Audit Log'], ['audit', 'Audit trail']],
  adm: [['dash', 'Dashboard'], ['ingest', 'Ingestion'], ['admin', 'Admin console']],
}
const TITLES = { dash: 'Dashboard', docs: 'Documents & summaries', disc: 'Discrepancies', ver: 'Doc Audit Log', ingest: 'Ingestion',
  signoff: 'GxP sign-off', audit: 'Audit trail', admin: 'Admin console' }

export default function App() {
  const [user, setUser] = useState(null)
  const [route, setRoute] = useState({ view: 'dash' })
  const [study, setStudy] = useState('')
  const [studies, setStudies] = useState([])
  const [tick, setTick] = useState(0)          // bump to refresh pages after actions

  const loadMe = () => api('/me').then((u) => {
    setUser(u); setStudies(u.studies)
    setStudy((s) => s && u.studies.some((x) => x.study_id === s) ? s : u.default_study)
  })
  useEffect(() => { if (hasToken()) loadMe().catch(() => {}) }, [])
  useEffect(() => {
    const out = () => setUser(null)
    window.addEventListener('tl-logout', out)
    return () => window.removeEventListener('tl-logout', out)
  }, [])

  if (!user) return <Login onLogin={() => { setRoute({ view: 'dash' }); loadMe() }} />

  const nav = NAV[user.role]
  const view = nav.some(([k]) => k === route.view) ? route.view : 'dash'
  const go = (r) => setRoute(typeof r === 'string' ? { view: r } : r)
  const refresh = () => { setTick((t) => t + 1); loadMe() }
  const props = { user, study, go, route, tick, refresh }
  const initials = user.role_name.split(' ').filter((w) => /^[A-Z]/.test(w)).map((w) => w[0]).join('').slice(0, 3)
  const cur = studies.find((s) => s.study_id === study)

  return (
    <div className="shell">
      <nav className="side" aria-label="Main menu">
        <div className="brand" style={{ padding: '0 8px 14px' }}><Logo size={28} />TrialLens</div>
        <div className="label">STUDY</div>
        {studies.length ? (
          <select value={study} onChange={(e) => setStudy(e.target.value)} aria-label="Study">
            {studies.map((s) => <option key={s.study_id} value={s.study_id}>{s.study_id} · {s.phase || 'phase ?'}</option>)}
          </select>
        ) : <div className="small" style={{ color: '#B8D3EC', padding: '0 8px' }}>No documents yet</div>}
        {cur && <div className="small" style={{ color: '#B8D3EC', padding: '4px 8px' }}>{cur.docs} current documents</div>}
        <div className="label">MAIN MENU</div>
        {nav.map(([k, l]) => <button key={k} className={`nav ${k === view ? 'on' : ''}`} onClick={() => go(k)}>{l}</button>)}
        <div className="label">GENERAL</div>
        <button className="nav" style={{ color: '#FFB4A8' }} onClick={() => { setToken(''); setUser(null) }}>Log out</button>
        <div style={{ marginTop: 'auto', fontSize: 12, color: '#B8D3EC', padding: 8, lineHeight: 1.5 }}>De-identified data · every action audited</div>
      </nav>

      <main className="main">
        <div className="topbar">
          <h1 style={{ fontSize: 20 }}>{TITLES[view]}</h1>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
            <span className="avatar" aria-hidden="true">{initials}</span>
            <span style={{ fontSize: 14, fontWeight: 600 }}>{user.role_name}</span>
          </div>
        </div>
        {view === 'dash' && <Dashboard {...props} />}
        {view === 'docs' && <Documents {...props} />}
        {view === 'disc' && <Discrepancies {...props} />}
        {view === 'ver' && <DocAuditLog {...props} />}
        {view === 'ingest' && <Ingestion {...props} />}
        {view === 'signoff' && <SignOff {...props} />}
        {view === 'audit' && <AuditTrail {...props} />}
        {view === 'admin' && <AdminConsole {...props} />}
      </main>

      <AskPanel user={user} study={study} go={go} onAnswer={() => setTick((t) => t + 1)} />
    </div>
  )
}
