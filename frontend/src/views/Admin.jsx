import { useEffect, useState } from 'react';
import * as api from '../api.js';
import Loading from '../components/Loading.jsx';

// The intents the backend can route per-model. Chain order is the default;
// an override pins one intent to one model.
const INTENTS = ['page', 'seeds', 'more', 'ask', 'recap', 'email'];

// The catalogue and stats shapes are the backend's to define; read them
// tolerantly so a rename on the server doesn't blank the page.
const pick = (o, ...keys) => {
  for (const k of keys) if (o && o[k] != null) return o[k];
  return null;
};
const modelId = (m) => (typeof m === 'string' ? m : pick(m, 'id', 'model', 'name') || '');
const contextOf = (m) => pick(m, 'contextLength', 'context_length', 'context');
// The catalogue carries this app's own rollup under `stats`; the stats endpoint
// returns those same fields at the top level.
const statsOf = (m) => (m && m.stats) || m;
const rateOf = (m) => pick(statsOf(m), 'okRate', 'ok_rate', 'successRate');
const latencyOf = (m) => pick(statsOf(m), 'p50Ms', 'p50', 'latencyMs');

function pct(v) {
  if (v == null) return '—';
  const n = Number(v);
  return `${Math.round(n <= 1 ? n * 100 : n)}%`;
}
function ms(v) {
  if (v == null) return '—';
  return `${Math.round(Number(v))}ms`;
}
function tokens(v) {
  if (v == null) return '—';
  const n = Number(v);
  return n >= 1000 ? `${Math.round(n / 1000)}k ctx` : `${n} ctx`;
}

export default function Admin({ onDone }) {
  const [models, setModels] = useState(null);
  const [chain, setChain] = useState([]);
  const [overrides, setOverrides] = useState({});
  const [stats, setStats] = useState(null);
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [loadErr, setLoadErr] = useState(null);

  const [testModel, setTestModel] = useState('');
  const [testIntent, setTestIntent] = useState('page');
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  useEffect(() => {
    let live = true;
    api
      .adminConfig()
      .then((r) => {
        if (!live) return;
        const c = Array.isArray(r.chain) ? r.chain : [];
        setChain(c);
        setOverrides(r.overrides && typeof r.overrides === 'object' ? r.overrides : {});
        if (c.length) setTestModel(c[0]);
      })
      .catch((e) => live && setLoadErr(e.message || "Couldn't read the config."));
    api
      .adminModels()
      .then((r) => live && setModels(r.models || r.data || []))
      .catch(() => live && setModels([]));
    api
      .adminStats()
      .then((r) => live && setStats(r.stats || r.models || []))
      .catch(() => live && setStats([]));
    return () => {
      live = false;
    };
  }, []);

  function move(i, delta) {
    setChain((c) => {
      const j = i + delta;
      if (j < 0 || j >= c.length) return c;
      const next = [...c];
      const [row] = next.splice(i, 1);
      next.splice(j, 0, row);
      return next;
    });
    setStatus(null);
  }

  function drop(i) {
    setChain((c) => c.filter((_, k) => k !== i));
    setStatus(null);
  }

  function add(id) {
    if (!id) return;
    setChain((c) => (c.includes(id) ? c : [...c, id]));
    setStatus(null);
  }

  async function save() {
    if (busy) return;
    setBusy(true);
    setStatus(null);
    const cleanOverrides = {};
    for (const [k, v] of Object.entries(overrides)) if (v) cleanOverrides[k] = v;
    try {
      const r = await api.saveAdminConfig({ chain, overrides: cleanOverrides });
      // The server echoes what it actually stored — trust that over our copy.
      if (Array.isArray(r.chain)) setChain(r.chain);
      if (r.overrides && typeof r.overrides === 'object') setOverrides(r.overrides);
      setStatus({ kind: 'good', text: 'Chain saved. Live from the next call.' });
    } catch (e) {
      setStatus({ kind: 'bad', text: e.message || "That didn't save." });
    } finally {
      setBusy(false);
    }
  }

  async function runTest() {
    if (testing || !testModel) return;
    setTesting(true);
    setTestResult(null);
    try {
      const r = await api.adminTest({ model: testModel, intent: testIntent });
      setTestResult(r);
    } catch (e) {
      setTestResult({ ok: false, error: e.message || 'The test call failed.' });
    } finally {
      setTesting(false);
    }
  }

  const catalogue = models || [];
  const options = [...new Set([...chain, ...catalogue.map(modelId)])].filter(Boolean);

  return (
    <div className="panel">
      <h2>Model chain</h2>
      <p className="sub">
        Free models come and go, and their JSON discipline varies by the week. Order the chain by
        what is behaving; the backend falls through on error, rate limit, or unparseable output.
      </p>

      {loadErr && <p className="formnote bad">{loadErr}</p>}
      {status && <p className={'formnote ' + (status.kind === 'good' ? 'good' : 'bad')}>{status.text}</p>}

      <h3>The chain, in order</h3>
      {chain.length === 0 ? (
        <p className="empty">No models in the chain. Add one from the catalogue below.</p>
      ) : (
        <ol className="chain">
          {chain.map((id, i) => (
            <li key={id}>
              <span className="rank">{i + 1}</span>
              <span className="mid">{id}</span>
              <span className="ctl">
                <button className="iconbtn" onClick={() => move(i, -1)} disabled={i === 0} title="Move up">
                  ↑
                </button>
                <button
                  className="iconbtn"
                  onClick={() => move(i, 1)}
                  disabled={i === chain.length - 1}
                  title="Move down"
                >
                  ↓
                </button>
                <button className="iconbtn" onClick={() => drop(i)} title="Remove from chain">
                  ×
                </button>
              </span>
            </li>
          ))}
        </ol>
      )}

      <h3>Per-intent overrides</h3>
      <p className="fhelp" style={{ marginBottom: 12 }}>
        Optional. An intent left on “chain order” uses the list above.
      </p>
      <div className="frow">
        {INTENTS.map((intent) => (
          <div className="field" key={intent}>
            <label className="flabel" htmlFor={`ov-${intent}`}>
              {intent}
            </label>
            <select
              id={`ov-${intent}`}
              className="finput"
              value={overrides[intent] || ''}
              onChange={(e) => {
                const v = e.target.value;
                setOverrides((o) => {
                  const next = { ...o };
                  if (v) next[intent] = v;
                  else delete next[intent];
                  return next;
                });
                setStatus(null);
              }}
            >
              <option value="">chain order</option>
              {options.map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>

      <div className="btnrow">
        <button className="btn" onClick={save} disabled={busy}>
          {busy ? 'Saving…' : 'Save chain'}
        </button>
        <button className="btn ghost" onClick={onDone} disabled={busy}>
          Back to the doors
        </button>
      </div>

      <h3>Free models on OpenRouter</h3>
      {models === null ? (
        <Loading>Reading the catalogue…</Loading>
      ) : catalogue.length === 0 ? (
        <p className="empty">No free models came back from the catalogue.</p>
      ) : (
        <div className="modellist">
          {catalogue.map((m) => {
            const id = modelId(m);
            const inChain = chain.includes(id);
            return (
              <div className="modelrow" key={id}>
                <span className="mname">
                  {id}
                  <span className="mmeta">
                    {tokens(contextOf(m))} · {pct(rateOf(m))} ok · {ms(latencyOf(m))} p50
                  </span>
                </span>
                <button className="btn tiny ghost" onClick={() => add(id)} disabled={inChain}>
                  {inChain ? 'In chain' : 'Add'}
                </button>
              </div>
            );
          })}
        </div>
      )}

      <h3>Test generation</h3>
      <div className="frow">
        <div className="field">
          <label className="flabel" htmlFor="test-model">
            Model
          </label>
          <select
            id="test-model"
            className="finput"
            value={testModel}
            onChange={(e) => setTestModel(e.target.value)}
          >
            <option value="">choose a model</option>
            {options.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label className="flabel" htmlFor="test-intent">
            Intent
          </label>
          <select
            id="test-intent"
            className="finput"
            value={testIntent}
            onChange={(e) => setTestIntent(e.target.value)}
          >
            {INTENTS.map((i) => (
              <option key={i} value={i}>
                {i}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="btnrow" style={{ marginTop: 4 }}>
        <button className="btn" onClick={runTest} disabled={testing || !testModel}>
          {testing ? 'Running…' : 'Run a test generation'}
        </button>
      </div>

      {testing && <Loading>Waiting on the model…</Loading>}
      {testResult && !testing && (
        <div style={{ marginTop: 18 }}>
          <p className={'formnote ' + (testResult.ok ? 'good' : 'bad')}>
            {testResult.ok ? 'Parsed cleanly' : testResult.error || 'Did not parse'}
            {testResult.latencyMs != null ? ` · ${ms(testResult.latencyMs)}` : ''}
          </p>
          <p className="flabel">Raw</p>
          <pre className="rawbox">{testResult.raw != null ? String(testResult.raw) : '—'}</pre>
          <p className="flabel">Parsed</p>
          <pre className="rawbox">
            {testResult.parsed != null ? JSON.stringify(testResult.parsed, null, 2) : '—'}
          </pre>
        </div>
      )}

      <h3>Recent behaviour</h3>
      {stats === null ? (
        <Loading>Reading the stats…</Loading>
      ) : stats.length === 0 ? (
        <p className="empty">Nothing logged yet.</p>
      ) : (
        <div className="tablewrap">
          <table className="stats">
            <thead>
              <tr>
                <th>Model</th>
                <th>Calls</th>
                <th>OK</th>
                <th>p50</th>
                <th>p95</th>
                <th>Last error</th>
              </tr>
            </thead>
            <tbody>
              {stats.map((s) => (
                <tr key={modelId(s)}>
                  <td>{modelId(s)}</td>
                  <td>{pick(s, 'calls', 'count') ?? '—'}</td>
                  <td>{pct(rateOf(s))}</td>
                  <td>{ms(pick(s, 'p50', 'p50Ms'))}</td>
                  <td>{ms(pick(s, 'p95', 'p95Ms'))}</td>
                  <td className="wrap">{pick(s, 'lastError', 'last_error') || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
