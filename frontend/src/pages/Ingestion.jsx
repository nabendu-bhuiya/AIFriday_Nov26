import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { Pill, useLoad } from '../ui'

const TYPES = [['', 'Auto-detect'], ['PROTOCOL', 'Clinical Protocol'], ['AMENDMENT', 'Protocol Amendment'], ['ICF', 'Informed Consent Form'],
  ['IB', "Investigator's Brochure"], ['SAP', 'Statistical Analysis Plan'], ['REG_SUBMISSION', 'Regulatory Submission'], ['DSMB_CHARTER', 'DSMB Charter'], ['OTHER', 'Other']]

export default function Ingestion({ refresh, go }) {
  const [data, reload, err] = useLoad('/ingest/jobs')
  const [msg, setMsg] = useState('')
  const [meta, setMeta] = useState({ doc_type: '', version: '', study_id: '', phase: '' })
  const file = useRef(null)
  const running = data?.jobs?.some((j) => ['queued', 'running'].includes(j.status))
  const wasRunning = useRef(false)

  useEffect(() => {
    if (running) { wasRunning.current = true; const t = setInterval(reload, 1500); return () => clearInterval(t) }
    if (wasRunning.current) { wasRunning.current = false; refresh() }
  }, [running, reload, refresh])

  const sync = async () => { try { const r = await api('/ingest/sync', { method: 'POST' }); setMsg(r.jobs.length ? `${r.jobs.length} new file(s) queued` : 'Repository already in sync'); reload() } catch (e) { setMsg(e.message) } }
  const upload = async () => {
    const f = file.current?.files?.[0]
    if (!f) return setMsg('Choose a file first')
    const form = new FormData()
    form.append('file', f)
    Object.entries(meta).forEach(([k, v]) => form.append(k, v))
    try { await api('/ingest/upload', { method: 'POST', form }); setMsg(`${f.name} queued`); file.current.value = ''; reload() } catch (e) { setMsg(e.message) }
  }

  return (
    <>
      <div className="grid2">
        <section className="card">
          <h2>Document repository (mock DMS)</h2>
          {data && <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Pill k="green">connected</Pill><span className="small muted mono" style={{ wordBreak: 'break-all' }}>{data.repository.path}</span></div>}
          {data && <div className="small">{data.repository.files} files in repository · {data.repository.indexed} versions indexed</div>}
          <div className="small muted">Drop PDF, DOCX, TXT or MD files into the folder, then sync. Only new or changed files are processed.</div>
          <div><button className="btn" onClick={sync}>Sync repository</button></div>
        </section>
        <section className="card">
          <h2>Upload a document</h2>
          <input type="file" ref={file} accept=".pdf,.docx,.txt,.md" />
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <label className="field">Type<select value={meta.doc_type} onChange={(e) => setMeta({ ...meta, doc_type: e.target.value })}>{TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
            <label className="field">Version<input placeholder="auto" value={meta.version} onChange={(e) => setMeta({ ...meta, version: e.target.value })} /></label>
            <label className="field">Study<input placeholder="auto" value={meta.study_id} onChange={(e) => setMeta({ ...meta, study_id: e.target.value })} /></label>
            <label className="field">Phase<select value={meta.phase} onChange={(e) => setMeta({ ...meta, phase: e.target.value })}>{['', 'Phase I', 'Phase II', 'Phase III'].map((p) => <option key={p} value={p}>{p || 'Auto-detect'}</option>)}</select></label>
          </div>
          <div><button className="btn" onClick={upload}>Upload & ingest</button></div>
        </section>
      </div>
      {msg && <div className="banner ok">{msg}</div>}
      {err && <div className="err">{err}</div>}
      <section className="card">
        <h2>Ingestion agent runs</h2>
        <div className="small muted">Parse → detect metadata → HIPAA de-identification → section split & ChromaDB index → one digest call (executive + role summaries + facts) → verifier → consistency judge</div>
        {(data?.jobs || []).map((j) => (
          <div key={j.id} style={{ borderTop: '1px solid #EAF2FA', paddingTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <b>{j.file_name}</b><Pill k={j.status === 'done' ? 'green' : j.status === 'error' ? 'red' : j.status === 'duplicate' ? 'grey' : 'amber'}>{j.status}</Pill>
              <span className="small muted">{j.created_at?.replace('T', ' ')} · {j.user}</span>
              {['done', 'duplicate'].includes(j.status) && j.doc_id &&
                <button className="btn" style={{ marginLeft: 'auto' }} onClick={() => go({ view: 'docs', id: j.doc_id })}>View summary</button>}
            </div>
            <div className="steps">{j.steps.map((s) => (
              <div key={s.name} className={`step ${s.status}`}><b>{s.status === 'running' && <span className="spin" />} {s.name}</b>{s.detail || s.status}</div>
            ))}</div>
            {j.error && <div className="err">{j.error}</div>}
          </div>
        ))}
        {data && !data.jobs.length && <div className="small muted">No runs yet.</div>}
      </section>
    </>
  )
}
