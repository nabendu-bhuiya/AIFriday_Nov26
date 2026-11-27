import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import { Cite } from './ui'

function Answer({ m, go }) {
  if (m.error) return <div className="a blocked">{m.error}</div>
  const r = m.res
  const t = r.trace || {}
  const meta = [r.grounded != null && `Grounded ${Number(r.grounded).toFixed(2)}`, r.cached ? `cache hit · 0 tokens` : t.tokens != null && `${t.tokens.toLocaleString()} tok`,
    t.latency_ms != null && `${(t.latency_ms / 1000).toFixed(1)} s`, t.trace_id].filter(Boolean).join(' · ')
  if (r.status === 'blocked') return <div className="a blocked"><b>{r.message}</b><span className="meta">Logged to audit trail · {t.trace_id}</span></div>
  if (r.status === 'withheld') return (
    <div className="a withheld"><b>{r.message}</b>
      <div>{r.sources.map((s) => <Cite key={s.id} c={s} />)}</div><span className="meta">{meta}</span></div>
  )
  if (r.status === 'insufficient') return <div className="a">{r.message}<span className="meta">{meta}</span></div>
  return (
    <div className="a">
      {r.claims.map((c, i) => <div key={i}>{c.text} {c.cites.map((x) => <Cite key={x.id} c={x} onFinding={(id) => go({ view: 'disc', id })} />)}</div>)}
      <span className="meta">{r.disclaimer} · {meta}</span>
    </div>
  )
}

export default function AskPanel({ user, study, go, onAnswer }) {
  const [msgs, setMsgs] = useState([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const end = useRef(null)
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs, busy])

  const send = async (text) => {
    const question = (text ?? q).trim()
    if (!question || busy) return
    setQ(''); setBusy(true)
    setMsgs((m) => [...m, { q: question }])
    try {
      const res = await api('/ask', { method: 'POST', body: { question, study } })
      setMsgs((m) => [...m, { res }])
      onAnswer?.()
    } catch (e) { setMsgs((m) => [...m, { error: e.message }]) }
    setBusy(false)
  }

  return (
    <aside className="ask" aria-label="Ask TrialLens">
      <div><h2 style={{ fontSize: 17 }}>Ask TrialLens</h2>
        <div className="small muted">{study || 'No study'} · answers cite sources · role-filtered</div></div>
      <div className="msgs">
        {!msgs.length && <div className="small muted">Ask about the trial documents your role can access. Every claim links to its source page.</div>}
        {msgs.map((m, i) => m.q ? <div key={i} className="q">{m.q}</div> : <Answer key={i} m={m} go={go} />)}
        {busy && <div className="a"><span><span className="spin" /> Agents working: guard → route → retrieve → answer → verify</span></div>}
        <div ref={end} />
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        <input className="input" style={{ flex: 1, minWidth: 0, height: 46, fontSize: 14 }} aria-label="Ask a question" placeholder="Ask about the documents…"
          value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && send()} />
        <button className="send" aria-label="Send" onClick={() => send()} disabled={busy}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" aria-hidden="true"><path d="M4 12l16-8-6 16-2-7z" /></svg>
        </button>
      </div>
    </aside>
  )
}
