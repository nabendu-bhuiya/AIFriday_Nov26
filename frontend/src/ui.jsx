import { useCallback, useEffect, useState } from 'react'
import { api } from './api'

export function useLoad(path, deps = []) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const reload = useCallback(() => {
    if (!path) return
    api(path).then((d) => { setData(d); setError('') }).catch((e) => setError(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps])
  useEffect(() => { reload() }, [reload])
  return [data, reload, error]
}

export const Pill = ({ k, children }) => <span className={`pill ${k || ''}`}>{children ?? k}</span>

export function Ring({ value, size = 88, color = '#1F6FB2', label }) {
  const v = value ?? 0
  const inner = Math.round(size * 0.73)
  return (
    <div className="ring" style={{ width: size, height: size, background: `conic-gradient(${color} 0 ${v}%, #D6E4F0 ${v}% 100%)` }}>
      <div style={{ width: inner, height: inner }}>
        <span style={{ fontSize: size > 80 ? 22 : 18, fontWeight: 600, color: '#1E5A8E' }}>{value == null ? '—' : `${v}%`}</span>
        {label && <span style={{ fontSize: 10, color: '#4A5768' }}>{label}</span>}
      </div>
    </div>
  )
}

export function Bars({ rows, color = '#1F6FB2' }) {
  const max = Math.max(1, ...rows.map((r) => r.n))
  if (!rows.length) return <div className="muted small">Nothing yet</div>
  return rows.map((r) => (
    <div key={r.label} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}><span>{r.label}</span><b>{r.n}</b></div>
      <div className="bar" style={{ height: 10, flex: 'none' }}><div style={{ height: 10, width: `${(r.n / max) * 100}%`, background: color }} /></div>
    </div>
  ))
}

export const level = (v) => (v == null ? ['—', '#8A97A6', '#4A5768'] : v >= 85 ? ['Good', '#067647', '#05603A'] : v >= 70 ? ['Watch', '#C27C0E', '#7A4504'] : ['Act', '#B42318', '#912018'])

export function Modal({ title, onClose, children }) {
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={title}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2>{title}</h2>
          <button className="linkbtn" onClick={onClose}>Close</button>
        </div>
        {children}
      </div>
    </div>
  )
}

/** A citation chip; clicking opens the de-identified source chunk. */
export function Cite({ c, onFinding }) {
  const [src, setSrc] = useState(null)
  if (!c?.id) return null
  const isFinding = /^DSC-/.test(c.id)
  const open = () => {
    if (isFinding) return onFinding?.(c.id)
    if (!/-p\d+-c\d+$/.test(c.id)) return
    api(`/chunks/${encodeURIComponent(c.id)}`).then(setSrc).catch((e) => setSrc({ error: e.message }))
  }
  return (
    <>
      <button className="cite" onClick={open} title="Open source">{c.label || c.id}</button>
      {src && (
        <Modal title={src.error ? 'Source unavailable' : `${src.doc} · page ${src.page}`} onClose={() => setSrc(null)}>
          {src.error ? <div className="err">{src.error}</div> : <>
            <div className="small muted">Section: {src.section} · <span className="mono">{src.id}</span> · de-identified text</div>
            <pre>{src.text}</pre>
          </>}
        </Modal>
      )}
    </>
  )
}

export function ReasonModal({ title, label = 'Reason (written to the audit trail)', onSubmit, onClose, password = false, meaning = false }) {
  const [reason, setReason] = useState('')
  const [pwd, setPwd] = useState('')
  const [mean, setMean] = useState('Reviewed and approved')
  const [err, setErr] = useState('')
  const go = async () => {
    try { await onSubmit({ reason, password: pwd, meaning: mean }); onClose() } catch (e) { setErr(e.message) }
  }
  return (
    <Modal title={title} onClose={onClose}>
      {meaning && <label className="field">Meaning of signature
        <select value={mean} onChange={(e) => setMean(e.target.value)}>
          <option>Reviewed and approved</option><option>Reviewed - accurate and complete</option><option>Authored / responsible</option>
        </select></label>}
      {!password && <label className="field">{label}<textarea className="input" value={reason} onChange={(e) => setReason(e.target.value)} /></label>}
      {password && <label className="field">Re-enter password to e-sign<input type="password" value={pwd} onChange={(e) => setPwd(e.target.value)} /></label>}
      {err && <div className="err">{err}</div>}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button className="btn secondary" onClick={onClose}>Cancel</button>
        <button className="btn" onClick={go}>{password ? 'Apply e-signature' : 'Submit'}</button>
      </div>
    </Modal>
  )
}
