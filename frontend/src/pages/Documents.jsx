import { useEffect, useState } from 'react'
import { api, qs } from '../api'
import { Cite, Pill, ReasonModal, useLoad } from '../ui'

const STATUS = { draft: 'AI draft · awaiting reviewer', reviewed: 'Reviewer approved · awaiting QA e-signature', e_signed: 'E-signed GxP record',
  rejected: 'Rejected by QA', flagged: 'Flagged for correction', none: 'No summary' }

export default function Documents({ user, study, route, tick, refresh, go }) {
  const [docs] = useLoad(`/documents${qs({ study })}`, [tick])
  const [sel, setSel] = useState(route.id || null)
  const [d, setD] = useState(null)
  const [flag, setFlag] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => { if (!sel && docs?.length) setSel((docs.find((x) => x.current) || docs[0]).id) }, [docs, sel])
  useEffect(() => { if (sel) api(`/documents/${sel}`).then(setD).catch((e) => setErr(e.message)) }, [sel, tick])

  if (docs && !docs.length) return <div className="empty">No documents in your role scope yet.</div>
  const approve = async () => { try { await api(`/documents/${sel}/approve`, { method: 'POST' }); refresh() } catch (e) { setErr(e.message) } }
  const st = d?.output?.status || 'none'

  return (
    <div className="row" style={{ alignItems: 'flex-start' }}>
      <div style={{ flex: '1 1 220px', maxWidth: 270, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {(docs || []).map((x) => (
          <button key={x.id} onClick={() => { setSel(x.id); setErr('') }} className="card" style={{ cursor: 'pointer', textAlign: 'left', border: x.id === sel ? '2px solid #1F6FB2' : '2px solid transparent', font: 'inherit', gap: 2, padding: '10px 12px' }}>
            <span style={{ fontSize: 14, fontWeight: 600 }}>{x.type}</span>
            <span className="small muted">v{x.version} · {x.pages} pp · verified {x.verified}</span>
            <span style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>{!x.current && <Pill k="Superseded" />}<Pill k={x.summary_status}>{x.summary_status.replace('_', '-')}</Pill></span>
          </button>
        ))}
      </div>
      {d && (
        <section className="card" style={{ flex: '999 1 420px', padding: 20 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
            <div><h2 style={{ fontSize: 18 }}>{d.type} v{d.version}</h2>
              <div className="small muted">{d.title} · {d.study} · {d.phase || 'phase ?'} · {d.pages} pages · {d.redactions} PHI entities masked at ingest</div></div>
            <Pill k="green">Verified {d.claims_supported}/{d.claims_total} claims · from cache</Pill>
          </div>
          <div className="banner ai">AI-generated. Check the cited source before acting. Status: <b>{STATUS[st]}</b>{d.output?.detail?.startsWith('Flagged') ? ` · ${d.output.detail}` : ''}</div>

          <h3 style={{ fontSize: 15, marginTop: 4 }}>Executive summary</h3>
          {d.executive_summary.map((p, i) => <div key={i} className="claim">{p.text} <Cite c={p.cite} /></div>)}

          <h3 style={{ fontSize: 15, marginTop: 8 }}>{d.lens_name} · for {user.role_name}</h3>
          {d.lens.length ? d.lens.map((p, i) => <div key={i} className="claim">{p.text} <Cite c={p.cite} /></div>) : <div className="small muted">No role lens for this document type.</div>}

          {d.key_sections.length > 0 && <>
            <h3 style={{ fontSize: 15, marginTop: 8 }}>Key sections to read</h3>
            {d.key_sections.map((k, i) => <div key={i} className="claim"><b>{k.section}</b> - {k.why} <Cite c={k.cite} /></div>)}
          </>}

          <div className="small muted" style={{ borderTop: '1px solid #EAF2FA', paddingTop: 8 }}>
            Review effort for this document (estimate): manual ~{d.review_time.manual_min} min → assisted ~{d.review_time.assisted_min} min
          </div>
          {err && <div className="err">{err}</div>}
          {['com', 'cra', 'mr'].includes(user.role) && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button className="btn" disabled={!['draft', 'flagged'].includes(st)} onClick={approve}>Approve summary</button>
              <button className="btn secondary" onClick={() => setFlag(true)}>Flag an error</button>
            </div>
          )}
          {user.role === 'aud' && st === 'reviewed' && <div><button className="btn" onClick={() => go({ view: 'signoff' })}>Review & sign</button></div>}
        </section>
      )}
      {flag && <ReasonModal title="Flag an error in this summary" onClose={() => setFlag(false)}
        onSubmit={async ({ reason }) => { await api(`/documents/${sel}/flag`, { method: 'POST', body: { reason } }); refresh() }} />}
    </div>
  )
}
