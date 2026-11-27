import { useState } from 'react'
import { api, qs } from '../api'
import { Pill, useLoad } from '../ui'

const tone = (a) => (/BLOCK|DENIED|REJECT|DISMISS/.test(a) ? 'red' : /E_SIGN|APPROVE|VALIDATE|VERIFY/.test(a) ? 'green' : /RAISE|FLAG|CONFIG/.test(a) ? 'amber' : 'blue')

export default function AuditTrail({ tick }) {
  const [f, setF] = useState({ user: '', role: '', action: '' })
  const [data, reload, err] = useLoad(`/audit${qs(f)}`, [tick])
  const [busy, setBusy] = useState(false)
  const verify = async () => { setBusy(true); await api('/audit/verify', { method: 'POST' }); reload(); setBusy(false) }
  const csv = () => {
    const cols = ['id', 'ts', 'user', 'role', 'action', 'object', 'detail', 'prev_hash', 'hash']
    const body = [cols.join(','), ...data.entries.map((e) => cols.map((c) => `"${String(e[c] ?? '').replace(/"/g, '""')}"`).join(','))].join('\n')
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([body], { type: 'text/csv' })); a.download = 'triallens_audit_trail.csv'; a.click()
  }
  if (err) return <div className="empty err">{err}</div>
  if (!data) return <div className="empty"><span className="spin" /> Loading…</div>
  const ok = data.chain.ok
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div className={`banner ${ok ? 'ok' : 'bad'}`} style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', padding: '14px 16px' }}>
        <div style={{ flex: 1, minWidth: 240 }}><b>{ok ? `Hash chain verified · ${data.chain.entries.toLocaleString()} entries intact` : `Hash chain BROKEN at entry ${data.chain.broken_at}`}</b>
          <div className="small">Each entry stores SHA-256(previous hash + entry). Any edit breaks the chain from that point on. Read-only view.</div></div>
        <button className="btn secondary" onClick={verify} disabled={busy}>Re-verify chain</button>
        <button className="btn" onClick={csv}>Export CSV</button>
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <label className="field small">User<select value={f.user} onChange={(e) => setF({ ...f, user: e.target.value })}><option value="">All users</option>{data.users.map((u) => <option key={u}>{u}</option>)}</select></label>
        <label className="field small">Role<select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}><option value="">All roles</option>{data.roles.map((r) => <option key={r.code} value={r.code}>{r.name}</option>)}</select></label>
        <label className="field small">Action<select value={f.action} onChange={(e) => setF({ ...f, action: e.target.value })}><option value="">All actions</option>{data.actions.map((a) => <option key={a}>{a}</option>)}</select></label>
      </div>
      <section className="card" style={{ overflowX: 'auto', padding: '8px 12px' }}>
        <table style={{ minWidth: 980 }}>
          <thead><tr><th>Time</th><th>User · role</th><th>Action</th><th>Object</th><th>Detail</th><th>Prev hash</th><th>Hash</th></tr></thead>
          <tbody>{data.entries.map((e) => (
            <tr key={e.id}><td className="mono" style={{ whiteSpace: 'nowrap' }}>{e.ts.replace('T', ' ')}</td><td>{e.user} · {e.role}</td><td><Pill k={tone(e.action)}>{e.action}</Pill></td>
              <td>{e.object}</td><td style={{ color: '#33414F' }}>{e.detail}</td><td className="mono muted">{e.prev_hash.slice(0, 4)}…{e.prev_hash.slice(-2)}</td><td className="mono">{e.hash.slice(0, 4)}…{e.hash.slice(-2)}</td></tr>
          ))}</tbody>
        </table>
      </section>
    </div>
  )
}
