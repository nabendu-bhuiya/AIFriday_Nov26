import { useState } from 'react'
import { qs } from '../api'
import { Bars, Pill, Ring, level, useLoad } from '../ui'

function MyWork({ work, gxp, go }) {
  const [tab, setTab] = useState('pend')
  const items = tab === 'pend' ? work.pending : work.completed
  return (
    <section className={`work ${gxp ? 'gxp' : ''}`} aria-label="My Work">
      <h2 style={{ color: gxp ? '#7A1A12' : '#6B3D04' }}>{gxp ? 'My Work · GxP sign-off required' : 'My Work'}</h2>
      {gxp && <div className="small" style={{ color: '#33414F' }}>AI output stays a draft until reviewer approval, QA review and e-signature (21 CFR Part 11).</div>}
      <div className="tabs" role="tablist">
        <button className={`tab ${tab === 'pend' ? 'on' : ''}`} role="tab" aria-selected={tab === 'pend'} onClick={() => setTab('pend')}>Pending ({work.pending.length})</button>
        <button className={`tab ${tab === 'done' ? 'on' : ''}`} role="tab" aria-selected={tab === 'done'} onClick={() => setTab('done')}>Completed ({work.completed.length})</button>
      </div>
      <div className="scroll" style={{ maxHeight: 260 }}>
        {!items.length && <div className="small muted" style={{ padding: 8 }}>{tab === 'pend' ? 'Nothing pending. 🎉' : 'No completed actions yet.'}</div>}
        {items.map((x, i) => (
          <div className="item" key={i}>
            <Pill k={x.p} />
            <div style={{ flex: 1, minWidth: 0 }}><div style={{ fontSize: 13, fontWeight: 500, lineHeight: 1.35 }}>{x.t}</div><div className="small muted">{x.sub}</div></div>
            <button className="btn" onClick={() => go(x.link)}>{x.btn}</button>
          </div>
        ))}
      </div>
    </section>
  )
}

function Scorecard({ sc, study }) {
  return (
    <section className="card" style={{ flex: '1 1 380px' }}>
      <div style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
        <Ring value={sc.overall} label="confidence" />
        <div><h2>Study intelligence scorecard</h2><div className="small muted">{study} · your lens · hover a row for the finding</div></div>
      </div>
      {sc.rows.map((r) => {
        const [tag, c, ink] = level(r.value)
        return (
          <div key={r.name} title={r.finding} style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <span style={{ flex: '0 0 170px', fontSize: 13, fontWeight: 500 }}>{r.name}</span>
            <div className="bar"><div style={{ width: `${r.value ?? 0}%`, background: c }} /></div>
            <span style={{ width: 40, fontSize: 13, fontWeight: 600, textAlign: 'right' }}>{r.value == null ? '—' : `${r.value}%`}</span>
            <span style={{ width: 44, fontSize: 12, fontWeight: 600, color: ink }}>{tag}</span>
          </div>
        )
      })}
    </section>
  )
}

function AuditorPanels({ p }) {
  return (
    <>
      <section className="card">
        <h2>AI output lifecycle</h2>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', fontSize: 14 }}>
          {p.lifecycle.map((s, i) => (
            <span key={s.label} style={{ display: 'contents' }}>
              {i > 0 && <span aria-hidden="true">→</span>}
              <span style={{ border: '1px solid #C5CED8', borderRadius: 8, padding: '8px 14px', background: ['#fff', '#FFF8EC', '#DCEBF8', '#EEF1F5'][i] }}><b>{s.n}</b> {s.label}</span>
            </span>
          ))}
        </div>
      </section>
      <div className="grid2">
        <section className="card" style={{ overflowX: 'auto' }}>
          <h2>Document version control</h2>
          <div className="scroll"><table><thead><tr><th>Document</th><th>Version</th><th>Effective</th><th>Status</th></tr></thead>
            <tbody>{p.version_table.map((v, i) => <tr key={i}><td>{v.doc}</td><td className="mono">v{v.version}</td><td>{v.date}</td><td><Pill k={v.status === 'Active' ? 'green' : 'grey'}>{v.status}</Pill></td></tr>)}</tbody></table></div>
        </section>
        <section className="card">
          <h2>Traceability{p.trace ? ` · finding ${p.trace.finding}` : ''}</h2>
          {p.trace ? <>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', fontSize: 13 }}>
              <span className="pill blue mono">{p.trace.source}</span>→<span className="pill blue">Consistency agent · {p.trace.agent}</span>→
              <span className="pill amber">Human: {p.trace.decision}</span>→<span className="pill green">Audit <span className="mono">{p.trace.audit}</span></span>
            </div>
            <div className="small muted">Every finding links to its source page, the agent run that produced it, the human decision and a hash-chained audit entry.</div>
          </> : <div className="small muted">No findings yet.</div>}
          <h2 style={{ marginTop: 6 }}>Superseded but still referenced</h2>
          {p.superseded_refs.length ? p.superseded_refs.map((r, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 10, fontSize: 13, borderTop: '1px solid #EAF2FA', paddingTop: 8 }}>
              <span>{r.to_type} v{r.ref_version} ← cited by {r.from}</span><Pill k="High">CAPA</Pill></div>
          )) : <div className="small muted">None - all references point to current versions.</div>}
        </section>
      </div>
    </>
  )
}

export default function Dashboard({ user, study, go, tick }) {
  const [d, , err] = useLoad(`/dashboard${qs({ study })}`, [tick])
  if (err) return <div className="empty err">{err}</div>
  if (!d) return <div className="empty"><span className="spin" /> Loading…</div>
  const first = user.name.startsWith('Dr.') ? user.name : user.name.split(' ')[0]
  const hour = new Date().getHours()
  const hello = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
  if (d.empty) return (
    <>
      <section className="greet"><div><h2 style={{ fontSize: 18, color: '#1E5A8E' }}>{hello}, {first}</h2><p className="small" style={{ margin: 0 }}>{d.greet}</p></div></section>
      <div className="empty">No documents ingested yet. {['com', 'adm'].includes(user.role) ? <>Open <button className="linkbtn" onClick={() => go('ingest')}>Ingestion</button> and sync the repository.</> : 'Ask your Clinical Operations Manager to ingest the study documents.'}</div>
    </>
  )
  const p = d.panels
  return (
    <>
      <section className="greet">
        <div style={{ flex: '1 1 240px' }}><h2 style={{ fontSize: 18, color: '#1E5A8E' }}>{hello}, {first}</h2>
          <p className="small" style={{ margin: 0, color: '#2A4A66' }}>{d.greet} {d.study} · {d.phase || 'phase not detected'}</p></div>
        <div className="kpis" style={{ flex: '2 1 460px' }}>
          {d.kpis.map((k) => <div className="kpi" key={k.label} title={k.note}><b>{k.value}</b><span>{k.label}</span></div>)}
        </div>
      </section>

      <div className="row">
        <MyWork work={d.work} gxp={user.role === 'aud'} go={go} />
        <Scorecard sc={d.scorecard} study={d.study} />
      </div>

      {user.role === 'aud' ? <AuditorPanels p={p} /> : (
        <div className="grid2">
          <section className="card"><h2>Discrepancies by status</h2><Bars rows={p.findings_by_status} color="#E58C8A" /></section>
          <section className="card"><h2>{user.role === 'adm' ? 'Documents indexed' : 'My open items by topic'}</h2>
            <Bars rows={user.role === 'adm' ? p.docs_by_type : p.my_topics} color={user.role === 'adm' ? '#1F6FB2' : '#F2A65A'} /></section>
          <section className="card">
            <h2>Review effort · manual vs assisted</h2>
            <div style={{ display: 'flex', gap: 24, alignItems: 'baseline', flexWrap: 'wrap' }}>
              <div><div className="small muted">Manual review</div><div style={{ fontSize: 32, fontWeight: 600, color: '#8A97A6' }}>{d.review_time.manual_h} h</div></div>
              <div><div className="small muted">With TrialLens</div><div style={{ fontSize: 32, fontWeight: 600, color: '#1E5A8E' }}>{d.review_time.assisted_h} h</div></div>
              <Pill k="green">{d.review_time.saved_pct}% less effort</Pill>
            </div>
            <div className="small muted">{d.review_time.pages} pages in your scope · {d.review_time.basis}</div>
          </section>
          {user.role !== 'adm' && <section className="card"><h2>Documents indexed</h2><Bars rows={p.docs_by_type} /></section>}
        </div>
      )}
    </>
  )
}
