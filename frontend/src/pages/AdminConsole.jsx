import { useEffect, useState } from 'react'
import { api } from '../api'
import { Pill, useLoad } from '../ui'
import AuditTrail from './AuditTrail'

const OUT = { Answered: 'green', Blocked: 'red', Withheld: 'amber', 'Cache hit': 'blue', Insufficient: 'grey', Ingested: 'green', Completed: 'green', Error: 'red', Duplicate: 'grey' }
const fmt = (n) => Math.round(n || 0).toLocaleString()

function Observability({ openTrace }) {
  const [d, reload, err] = useLoad('/admin/observability')
  const [ping, setPing] = useState(null)
  const test = async () => { setPing('…'); try { setPing(await api('/health/llm', { method: 'POST' })); reload() } catch (e) { setPing([{ model: 'LLM', ok: false, error: e.message }]) } }
  if (err) return <div className="err">{err}</div>
  if (!d) return <div className="empty"><span className="spin" /></div>
  const maxTok = Math.max(1, ...d.models.map((m) => m.tok))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div className="kpis" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))' }}>
        {d.kpis.map((k) => <div className="kpi" key={k.label} style={{ border: '1px solid #DDE3EA', padding: '12px 14px' }}><span>{k.label}</span><b style={{ fontSize: 24 }}>{k.value}</b><span className="small muted">{k.note}</span></div>)}
      </div>
      <section className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}><h2>Agent pipeline · average per Ask request</h2><span className="small muted">Rules first, gpt-4.1-mini answers and verifies, gpt-4.1 judges consistency</span></div>
        <div className="steps">{d.pipeline.map((p) => (
          <div className="step" key={p.name}><b>{p.name}</b><span className="mono">{p.model}</span><div>{fmt(p.ms)} ms · {fmt(p.tok)} tok · {p.n} runs</div></div>
        ))}{!d.pipeline.length && <span className="small muted">No requests yet. Ask a question in the panel on the right.</span>}</div>
      </section>
      <div className="grid2">
        <section className="card"><h2>Tokens by model</h2>
          {d.models.map((m) => (
            <div key={m.name} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}><span className="mono">{m.name}</span><span className="muted">{fmt(m.tok)} tok · ${m.cost.toFixed(4)} · {fmt(m.cached)} cached</span></div>
              <div className="bar" style={{ height: 10, flex: 'none' }}><div style={{ height: 10, width: `${(m.tok / maxTok) * 100}%`, background: '#1F6FB2' }} /></div>
            </div>))}
          {!d.models.length && <span className="small muted">No LLM calls yet.</span>}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}><button className="btn secondary" onClick={test}>Test LLM connection</button>
            {Array.isArray(ping) && ping.map((p) => <Pill key={p.model} k={p.ok ? 'green' : 'red'}>{p.model.split('/').pop()} {p.ok ? `ok · ${p.ms} ms` : 'failed'}</Pill>)}{ping === '…' && <span className="spin" />}</div>
          {Array.isArray(ping) && ping.filter((p) => !p.ok).map((p) => <div key={p.model} className="err small">{p.error}</div>)}
        </section>
        <section className="card"><h2>Where tokens were saved</h2>
          {d.savings.map((s) => <div key={s.what} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 14, borderTop: '1px solid #EEF1F5', paddingTop: 8 }}><span>{s.what} <span className="small muted">×{s.n}</span></span><b style={{ color: '#05603A' }}>−{fmt(s.saved)}</b></div>)}
          {!d.savings.length && <span className="small muted">Savings appear as users ask questions and open summaries.</span>}
        </section>
      </div>
      <section className="card"><h2>Context caching levels</h2>
        <table><thead><tr><th>Level</th><th>Status</th><th>How</th></tr></thead>
          <tbody>{d.cache_levels.map((c) => <tr key={c.level}><td><b>{c.level}</b></td><td>{c.stat === 'deferred' ? <Pill k="grey">deferred</Pill> : c.stat}</td><td className="muted">{c.note}</td></tr>)}</tbody></table>
      </section>
      <section className="card" style={{ overflowX: 'auto' }}><h2>Recent traces</h2>
        <table style={{ minWidth: 820 }}><thead><tr><th>Trace</th><th>User · role</th><th>Intent</th><th>Question</th><th>Tokens</th><th>Latency</th><th>Grounded</th><th>Outcome</th></tr></thead>
          <tbody>{d.traces.map((t) => (
            <tr key={t.id}><td><button className="linkbtn mono" onClick={() => openTrace(t.id)}>{t.id}</button></td><td>{t.user} · {t.role}</td><td>{t.intent}</td>
              <td className="small" style={{ maxWidth: 240 }}>{t.question}</td><td>{fmt(t.tokens)}</td><td>{(t.latency_ms / 1000).toFixed(2)} s</td>
              <td>{t.grounded != null ? t.grounded.toFixed(2) : '–'}</td><td><Pill k={OUT[t.outcome] || 'blue'}>{t.outcome}</Pill></td></tr>))}</tbody></table>
      </section>
    </div>
  )
}

function Guardrails() {
  const [d, reload, err] = useLoad('/admin/guardrails')
  const [thr, setThr] = useState('')
  useEffect(() => { if (d) setThr(d.threshold) }, [d])
  if (err) return <div className="err">{err}</div>
  if (!d) return <div className="empty"><span className="spin" /></div>
  const toggle = async (g) => { await api(`/admin/guardrails/${g.id}`, { method: 'POST', body: { on: !g.on } }); reload() }
  const saveThr = async () => { await api('/admin/threshold', { method: 'POST', body: { value: Number(thr) } }); reload() }
  return (
    <div className="row" style={{ alignItems: 'flex-start' }}>
      <section className="card" style={{ flex: '1 1 520px' }}><h2>Guardrails</h2>
        {d.guards.map((g) => (
          <div key={g.id} style={{ display: 'flex', gap: 14, alignItems: 'center', borderTop: '1px solid #EEF1F5', padding: '10px 0' }}>
            <div style={{ flex: 1, minWidth: 0 }}><div style={{ fontSize: 14, fontWeight: 600 }}>{g.name} <Pill k="grey">{g.stage}</Pill></div><div className="small muted">{g.desc}</div></div>
            <span className="small muted" style={{ whiteSpace: 'nowrap' }}>{g.hits}</span>
            <button className={`switch ${g.on ? 'on' : ''}`} role="switch" aria-checked={g.on} aria-label={g.name} onClick={() => toggle(g)}><span /></button>
          </div>))}
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', borderTop: '1px solid #EEF1F5', paddingTop: 10 }}>
          <label className="field small">Grounding threshold<input type="number" step="0.05" min="0.5" max="1" value={thr} onChange={(e) => setThr(e.target.value)} style={{ width: 120 }} /></label>
          <button className="btn secondary" onClick={saveThr}>Save threshold</button>
        </div>
        <div className="small muted">Every change is written to the audit trail.</div>
      </section>
      <section className="card" style={{ flex: '1 1 380px' }}><h2>Responsible AI scorecard</h2>
        {d.rai.map((r) => (
          <div key={r.p} style={{ borderTop: '1px solid #EEF1F5', paddingTop: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}><b style={{ fontSize: 14 }}>{r.p}</b><b style={{ fontSize: 13, color: '#05603A' }}>{r.m}</b></div>
            <div className="small muted">{r.how}</div>
          </div>))}
      </section>
    </div>
  )
}

function AgentTrace({ id, setId }) {
  const [list] = useLoad('/admin/observability')
  const [t, setT] = useState(null)
  const tid = id || list?.traces?.[0]?.id
  useEffect(() => { if (tid) api(`/admin/traces/${tid}`).then(setT).catch(() => setT(null)) }, [tid])
  if (!list) return <div className="empty"><span className="spin" /></div>
  if (!tid) return <div className="empty">No traces yet.</div>
  const color = (s) => (s.status === 'error' ? '#B42318' : s.status === 'blocked' ? '#C27C0E' : /miss/.test(s.detail) ? '#8A97A6' : '#067647')
  return (
    <section className="card">
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <h2>Trace</h2>
        <select className="input" style={{ height: 38, fontSize: 13 }} value={tid} onChange={(e) => setId(e.target.value)}>
          {list.traces.map((x) => <option key={x.id} value={x.id}>{x.id} · {x.role} · {x.intent} · {x.question.slice(0, 50)}</option>)}
        </select>
      </div>
      {t && <>
        <div className="small muted">{t.user} · {t.role} · "{t.question}" · {fmt(t.tokens)} tokens · {(t.latency_ms / 1000).toFixed(2)} s · ${t.cost.toFixed(5)} · <Pill k={OUT[t.outcome] || 'blue'}>{t.outcome}</Pill></div>
        {t.spans.map((s) => (
          <div key={s.id} style={{ display: 'flex', gap: 12, borderTop: '1px solid #EEF1F5', padding: '10px 0', flexWrap: 'wrap' }}>
            <span className="dot" style={{ background: color(s) }} aria-hidden="true" />
            <div style={{ flex: '1 1 260px', minWidth: 0 }}><div style={{ fontSize: 14, fontWeight: 600 }}>{s.name} <span className="mono small muted" style={{ fontWeight: 400 }}>{s.model}</span></div><div className="small" style={{ color: '#33414F' }}>{s.detail}</div></div>
            <span className="small muted" style={{ width: 170 }}>{s.tokens_in || s.tokens_out ? `${fmt(s.tokens_in)} in / ${fmt(s.tokens_out)} out${s.cached_tokens ? ` · ${fmt(s.cached_tokens)} cached` : ''}` : '0 tok'}</span>
            <span className="mono small" style={{ width: 70, textAlign: 'right' }}>{fmt(s.latency_ms)} ms</span>
          </div>))}
      </>}
    </section>
  )
}

export default function AdminConsole({ route, tick }) {
  const [tab, setTab] = useState(route.tab || 'obs')
  const [traceId, setTraceId] = useState(null)
  useEffect(() => { if (route.tab) setTab(route.tab) }, [route])
  const tabs = [['obs', 'AI observability'], ['audit', 'Audit trail'], ['guard', 'Guardrails & Responsible AI'], ['trace', 'Agent trace']]
  return (
    <>
      <div className="tabs" role="tablist">{tabs.map(([k, l]) => <button key={k} role="tab" className={`tab ${tab === k ? 'on' : ''}`} onClick={() => setTab(k)}>{l}</button>)}</div>
      {tab === 'obs' && <Observability key={tick} openTrace={(id) => { setTraceId(id); setTab('trace') }} />}
      {tab === 'audit' && <AuditTrail tick={tick} />}
      {tab === 'guard' && <Guardrails />}
      {tab === 'trace' && <AgentTrace key={tick} id={traceId} setId={setTraceId} />}
    </>
  )
}
