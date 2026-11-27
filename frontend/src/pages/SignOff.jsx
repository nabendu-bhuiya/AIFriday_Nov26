import { useState } from 'react'
import { api, qs } from '../api'
import { Pill, ReasonModal, useLoad } from '../ui'

const KIND = { summary: 'AI summary', answer_withheld: 'Withheld answer', finding_dismissal: 'Discrepancy dismissal' }
const STAGE = { draft: 'AI draft · waiting for reviewer', reviewed: 'AI ✓ · Reviewer ✓ · QA review pending', e_signed: 'AI ✓ · Reviewer ✓ · QA ✓ · e-signed',
  rejected: 'Rejected by QA', flagged: 'Flagged by reviewer' }

export default function SignOff({ study, route, tick, refresh }) {
  const [rows, reload, err] = useLoad(`/signoff${qs({ study })}`, [tick])
  const [sign, setSign] = useState(null)
  const [rej, setRej] = useState(null)
  const done = () => { reload(); refresh() }
  return (
    <section className="card" style={{ padding: 20, border: '2px solid #B42318', overflowX: 'auto' }}>
      <h2 style={{ color: '#7A1A12' }}>GxP · Human sign-off required</h2>
      <div className="small">An AI output becomes a GxP record only after reviewer approval, QA review and an e-signature (user, time, meaning, password re-entry, hash-chained audit entry).</div>
      {err && <div className="err">{err}</div>}
      <table style={{ minWidth: 760 }}>
        <thead><tr><th>Output</th><th>Type</th><th>Approval trail</th><th>Detail</th><th>Status</th><th>Action</th></tr></thead>
        <tbody>
          {(rows || []).map((o) => (
            <tr key={o.id} className={route.id === o.id ? 'hl' : ''}>
              <td><b>{o.title}</b><div className="small muted mono">OUT-{o.id}</div></td>
              <td>{KIND[o.kind] || o.kind}</td>
              <td className="small">{STAGE[o.status]}{o.reviewer && <div className="muted">reviewer {o.reviewer}</div>}{o.qa_user && <div className="muted">QA {o.qa_user} · {o.sign_meaning}{o.audit_hash ? ` · audit ${o.audit_hash.slice(0, 4)}…${o.audit_hash.slice(-2)}` : ''}</div>}</td>
              <td className="small muted" style={{ maxWidth: 220 }}>{o.detail}</td>
              <td><Pill k={o.status}>{o.status.replace('_', '-')}</Pill></td>
              <td>{o.status === 'reviewed' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <button className="btn" onClick={() => setSign(o.id)}>Review & sign</button>
                  <button className="btn danger" onClick={() => setRej(o.id)}>Reject</button>
                </div>)}</td>
            </tr>
          ))}
          {rows && !rows.length && <tr><td colSpan={6} className="muted">No AI outputs yet.</td></tr>}
        </tbody>
      </table>
      {sign && <ReasonModal title={`E-sign OUT-${sign}`} password meaning onClose={() => setSign(null)}
        onSubmit={async ({ password, meaning }) => { await api(`/signoff/${sign}/sign`, { method: 'POST', body: { password, meaning } }); done() }} />}
      {rej && <ReasonModal title={`Reject OUT-${rej}`} onClose={() => setRej(null)}
        onSubmit={async ({ reason }) => { await api(`/signoff/${rej}/reject`, { method: 'POST', body: { reason } }); done() }} />}
    </section>
  )
}
