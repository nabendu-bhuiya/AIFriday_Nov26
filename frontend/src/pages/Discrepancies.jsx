import { useState } from 'react'
import { api, qs } from '../api'
import { Cite, Pill, ReasonModal, useLoad } from '../ui'

const RAISE = { com: 'Raise doc update', cra: 'Raise site query', mr: 'Send to safety' }
const OWNER = { com: 'Clin Ops', cra: 'CRA', mr: 'Medical' }
const lab = (id) => { const m = /([A-Z]+\d*)v([\w.]+)-p(\d+)/.exec(id || ''); return m ? `${m[1]} v${m[2]} p.${m[3]}` : id }

export default function Discrepancies({ user, study, route, tick, refresh }) {
  const [rows, reload, err] = useLoad(`/findings${qs({ study })}`, [tick])
  const [dismiss, setDismiss] = useState(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [show, setShow] = useState('active')
  const act = async (id, action, reason = '') => {
    await api(`/findings/${id}/action`, { method: 'POST', body: { action, reason } }); reload(); refresh()
  }
  const run = async () => {
    setBusy(true); setMsg('')
    try { const r = await api(`/consistency/run${qs({ study })}`, { method: 'POST' }); setMsg(`${r.summary} · ${r.trace_id} · ${r.tokens?.toLocaleString()} tokens`); reload(); refresh() }
    catch (e) { setMsg(e.message) }
    setBusy(false)
  }
  const canAct = ['com', 'cra', 'mr'].includes(user.role)
  const list = (rows || []).filter((f) => show === 'all' || !['resolved', 'dismissed'].includes(f.status))
  return (
    <section className="card" style={{ padding: 20, overflowX: 'auto' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <div className="tabs">
          <button className={`tab ${show === 'active' ? 'on' : ''}`} onClick={() => setShow('active')}>Active</button>
          <button className={`tab ${show === 'all' ? 'on' : ''}`} onClick={() => setShow('all')}>All</button>
        </div>
        <span className="small muted">{list.length} findings · Protocol, Amendments, ICF, IB, SAP and submission compared</span>
        {['com', 'mr', 'aud'].includes(user.role) && <button className="btn" style={{ marginLeft: 'auto' }} onClick={run} disabled={busy}>{busy ? 'Checking…' : 'Run consistency check'}</button>}
      </div>
      {msg && <div className="banner ok">{msg}</div>}
      {err && <div className="err">{err}</div>}
      <table style={{ minWidth: 820 }}>
        <thead><tr><th>ID</th><th>Item</th><th>Source A</th><th>Source B</th><th>Severity</th><th>Owner</th><th>Status</th>{canAct && <th>Action</th>}</tr></thead>
        <tbody>
          {list.map((f) => (
            <tr key={f.id} className={route.id === f.id ? 'hl' : ''}>
              <td className="mono">{f.id}</td>
              <td style={{ fontWeight: 600, maxWidth: 200 }}>{f.item}<div className="small muted" style={{ fontWeight: 400 }}>{f.rationale}</div></td>
              <td><b className="mono small">{f.doc_a}</b> {f.value_a} <Cite c={{ id: f.cite_a, label: lab(f.cite_a) }} /></td>
              <td><b className="mono small">{f.doc_b}</b> {f.value_b} <Cite c={{ id: f.cite_b, label: lab(f.cite_b) }} /></td>
              <td><Pill k={f.severity} /></td>
              <td>{OWNER[f.owner_role]}</td>
              <td><Pill k={f.status} />{f.decided_by && <div className="small muted">{f.decided_by}{f.reason ? `: ${f.reason}` : ''}</div>}</td>
              {canAct && <td>{f.status === 'open' ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <button className="btn" onClick={() => act(f.id, 'raise')}>{RAISE[user.role]}</button>
                  <button className="btn secondary" onClick={() => act(f.id, 'validate')}>Validate</button>
                  <button className="btn danger" onClick={() => setDismiss(f.id)}>Dismiss</button>
                </div>) : f.status === 'raised' ? <button className="btn secondary" onClick={() => act(f.id, 'validate', 'resolution confirmed')}>Mark validated</button> : null}
              </td>}
            </tr>
          ))}
          {!list.length && <tr><td colSpan={8} className="muted">No findings. Ingest at least two documents of the study, then run the consistency check.</td></tr>}
        </tbody>
      </table>
      <p className="small muted" style={{ margin: 0 }}>Agents never close a discrepancy themselves. Dismissing needs a reason, is written to the audit trail and goes to QA for GxP sign-off.</p>
      {dismiss && <ReasonModal title={`Dismiss ${dismiss}`} onClose={() => setDismiss(null)} onSubmit={({ reason }) => act(dismiss, 'dismiss', reason)} />}
    </section>
  )
}
