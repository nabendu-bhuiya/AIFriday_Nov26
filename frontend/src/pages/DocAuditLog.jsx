import { useState } from 'react'
import { api, qs } from '../api'
import { Pill, useLoad } from '../ui'

const tone = (s) => (s === 'Current' ? 'green' : s === 'Missing' ? 'red' : 'amber')

export default function DocAuditLog({ study, tick }) {
  const [groups, , err] = useLoad(`/versions${qs({ study })}`, [tick])
  const [sel, setSel] = useState(0)
  const [done, setDone] = useState('')
  if (err) return <div className="empty err">{err}</div>
  if (!groups) return <div className="empty"><span className="spin" /> Loading…</div>
  if (!groups.length) return <div className="empty">No documents yet.</div>
  const g = groups[Math.min(sel, groups.length - 1)]
  const request = async () => { await api(`/versions/request${qs({ study })}`, { method: 'POST', body: { doc_type: g.doc_type } }); setDone(g.name) }
  return (
    <div className="card" style={{ flexDirection: 'row', flexWrap: 'wrap', padding: 0, gap: 0, minHeight: 520, overflow: 'hidden' }}>
      <div style={{ flex: '1 1 220px', maxWidth: 280, borderRight: '1px solid #E3EAEE', padding: 12, display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div className="small muted" style={{ letterSpacing: '0.06em', padding: '4px 8px' }}>TRIAL MASTER FILE · {study}</div>
        {groups.map((x, i) => (
          <button key={x.doc_type} onClick={() => { setSel(i); setDone('') }}
            style={{ font: 'inherit', textAlign: 'left', border: 0, borderRadius: 8, padding: '10px 12px', cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: 2, background: i === sel ? '#DCEBF8' : 'transparent', color: '#0F1B2D' }}>
            <span style={{ fontSize: 14, fontWeight: 600 }}>{x.name}</span>
            <span className="small muted">{x.versions.length ? `v${x.versions[0].version} · ${x.versions.length} version${x.versions.length > 1 ? 's' : ''}` : 'no version'}</span>
            <span><Pill k={tone(x.status)}>{x.status}</Pill></span>
          </button>
        ))}
      </div>
      <div style={{ flex: '999 1 360px', minWidth: 0, padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div><h2 style={{ fontSize: 20 }}>{g.name}</h2><span className="small muted">Version history, ingestion record and compatibility checks</span></div>
        {g.status === 'Missing' ? (
          <div style={{ display: 'flex', gap: 16, alignItems: 'center', border: '1px dashed #E58C8A', borderRadius: 12, padding: 16, background: '#FFF7F6', flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: 200 }}><b>Expected document missing</b><div className="small muted">{g.checks[0]}</div></div>
            <button className="btn" onClick={request} disabled={done === g.name}>{done === g.name ? 'Requested ✓' : 'Request from owner'}</button>
          </div>
        ) : <>
          <h3 style={{ fontSize: 14 }}>Versions</h3>
          <table><thead><tr><th>Version</th><th>Date</th><th>Status</th><th>File</th><th>PHI masked</th><th>Ingested by</th></tr></thead>
            <tbody>{g.versions.map((v) => (
              <tr key={v.id}><td className="mono"><b>v{v.version}</b></td><td>{v.date}</td><td><Pill k={v.status} /></td><td className="small">{v.file} · {v.pages} pp</td><td>{v.redactions}</td><td className="small">{v.ingested_by}<div className="muted">{v.ingested_at?.replace('T', ' ')}</div></td></tr>
            ))}</tbody></table>
          <h3 style={{ fontSize: 14 }}>Version compatibility check</h3>
          {g.checks.map((c, i) => <div key={i} className={`banner ${/OUTDATED|outdated/.test(c) ? 'bad' : ''}`} style={{ background: /OUTDATED|outdated/.test(c) ? undefined : '#F2F7FD', fontSize: 14 }}>{c}</div>)}
        </>}
      </div>
    </div>
  )
}
