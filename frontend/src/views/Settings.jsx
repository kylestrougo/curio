import { useEffect, useState } from 'react';
import * as api from '../api.js';
import Loading from '../components/Loading.jsx';

const DEFAULTS = {
  enabled: false,
  topics: [],
  wildcard: true,
  sendHour: 8,
  frequency: 'daily',
};

function hourLabel(h) {
  const suffix = h < 12 ? 'am' : 'pm';
  const twelve = h % 12 === 0 ? 12 : h % 12;
  return `${String(h).padStart(2, '0')}:00 — ${twelve}${suffix}`;
}

// The browser's IANA timezone, so "send around 11pm" means the user's 11pm.
// Sent silently with every save; the server validates and falls back to its
// configured default when this comes back empty.
function browserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || '';
  } catch {
    return '';
  }
}

// Server-side clamps, mirrored so the editor never promises what a save
// would silently trim (email_.py caps topics at 15 entries of 80 chars).
const MAX_TOPICS = 15;
const MAX_TOPIC_CHARS = 80;

export default function Settings({ onDone, onPrefsSaved }) {
  const [prefs, setPrefs] = useState(null);
  const [draft, setDraft] = useState(''); // the tag being typed
  const [status, setStatus] = useState(null); // {kind:'bad'|'good', text}
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .getEmailPrefs()
      .then((r) => {
        if (!live) return;
        const p = { ...DEFAULTS, ...(r.prefs || r) };
        p.topics = Array.isArray(p.topics) ? p.topics : [];
        setPrefs(p);
      })
      .catch((e) => {
        if (!live) return;
        setPrefs({ ...DEFAULTS });
        setStatus({ kind: 'bad', text: e.message || "Couldn't read your preferences." });
      });
    return () => {
      live = false;
    };
  }, []);

  function set(key, value) {
    setPrefs((p) => ({ ...p, [key]: value }));
    setStatus(null);
  }

  function addTopic() {
    const t = draft.trim().slice(0, MAX_TOPIC_CHARS);
    if (!t || !prefs) return;
    if (prefs.topics.length >= MAX_TOPICS) return;
    // Case-insensitive dedupe: "Old Maps" and "old maps" are one interest.
    if (prefs.topics.some((x) => x.toLowerCase() === t.toLowerCase())) {
      setDraft('');
      return;
    }
    set('topics', [...prefs.topics, t]);
    setDraft('');
  }

  function removeTopic(topic) {
    set('topics', prefs.topics.filter((t) => t !== topic));
  }

  async function save() {
    if (busy || !prefs) return;
    setBusy(true);
    setStatus(null);
    // A typed-but-unadded tag still counts — losing it on save is the kind
    // of thing that teaches people to distrust forms.
    const pending = draft.trim();
    const topics = [...prefs.topics];
    if (
      pending &&
      topics.length < MAX_TOPICS &&
      !topics.some((x) => x.toLowerCase() === pending.toLowerCase())
    ) {
      topics.push(pending.slice(0, MAX_TOPIC_CHARS));
    }
    const body = {
      enabled: !!prefs.enabled,
      topics,
      wildcard: !!prefs.wildcard,
      sendHour: Number(prefs.sendHour),
      frequency: prefs.frequency,
      timezone: browserTimezone(),
    };
    try {
      const r = await api.putEmailPrefs(body);
      // The server echoes what it stored (it clamps the hour and the frequency).
      const stored = r && 'enabled' in r ? r : body;
      setPrefs((p) => ({ ...p, ...stored }));
      setDraft('');
      setStatus({ kind: 'good', text: 'Saved.' });
      if (onPrefsSaved) onPrefsSaved(); // home's topical doors refresh to match
    } catch (e) {
      setStatus({ kind: 'bad', text: e.message || "That didn't save." });
    } finally {
      setBusy(false);
    }
  }

  if (!prefs) {
    return (
      <div className="panel">
        <h2>Doors in your inbox</h2>
        <Loading>Fetching your preferences…</Loading>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2>Doors in your inbox</h2>
      <p className="sub">
        If you'd like, Curio can send you a few doors to walk through — the same kind you'd find on
        the home page, chosen around what you're curious about. Set nothing and nothing arrives.
      </p>

      {status && <p className={'formnote ' + (status.kind === 'good' ? 'good' : 'bad')}>{status.text}</p>}

      <label className="check">
        <input
          type="checkbox"
          checked={!!prefs.enabled}
          onChange={(e) => set('enabled', e.target.checked)}
        />
        <span className="ctext">
          Send me doors
          <span className="fhelp" style={{ display: 'block' }}>
            Turn this off whenever you like. It takes effect immediately.
          </span>
        </span>
      </label>

      <div className="field">
        <label className="flabel" htmlFor="curio-topic-input">
          Things you're curious about
        </label>
        {prefs.topics.length > 0 && (
          <div className="tag-row">
            {prefs.topics.map((t) => (
              <span className="tag" key={t}>
                {t}
                <button
                  type="button"
                  className="tag-x"
                  onClick={() => removeTopic(t)}
                  aria-label={`Remove ${t}`}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="tag-add">
          <input
            id="curio-topic-input"
            className="finput"
            type="text"
            value={draft}
            maxLength={MAX_TOPIC_CHARS}
            disabled={prefs.topics.length >= MAX_TOPICS}
            onChange={(e) => {
              setDraft(e.target.value);
              setStatus(null);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                addTopic();
              }
            }}
            placeholder={
              prefs.topics.length >= MAX_TOPICS
                ? 'That is plenty — remove one to add another.'
                : prefs.topics.length
                  ? 'Add another…'
                  : 'e.g. deep sea biology'
            }
          />
          <button
            type="button"
            className="btn ghost tag-add-btn"
            onClick={addTopic}
            disabled={!draft.trim() || prefs.topics.length >= MAX_TOPICS}
          >
            Add
          </button>
        </div>
        <p className="fhelp">
          Press Enter or Add after each one. Leave it empty and Curio will range widely on its own.
        </p>
      </div>

      <label className="check">
        <input
          type="checkbox"
          checked={!!prefs.wildcard}
          onChange={(e) => set('wildcard', e.target.checked)}
        />
        <span className="ctext">
          Include one wildcard door
          <span className="fhelp" style={{ display: 'block' }}>
            Something from a corner you'd never think to ask about.
          </span>
        </span>
      </label>

      <div className="frow">
        <div className="field">
          <label className="flabel" htmlFor="curio-hour">
            Send around
          </label>
          <select
            id="curio-hour"
            className="finput"
            value={String(prefs.sendHour)}
            onChange={(e) => set('sendHour', Number(e.target.value))}
          >
            {Array.from({ length: 24 }, (_, h) => (
              <option key={h} value={String(h)}>
                {hourLabel(h)}
              </option>
            ))}
          </select>
          {browserTimezone() && <p className="fhelp">In your local time ({browserTimezone()}).</p>}
        </div>
        <div className="field">
          <label className="flabel" htmlFor="curio-freq">
            How often
          </label>
          <select
            id="curio-freq"
            className="finput"
            value={prefs.frequency}
            onChange={(e) => set('frequency', e.target.value)}
          >
            <option value="daily">Every day</option>
            <option value="weekdays">Weekdays</option>
            <option value="weekly">Once a week</option>
          </select>
        </div>
      </div>

      <div className="btnrow">
        <button className="btn" onClick={save} disabled={busy}>
          {busy ? 'Saving…' : 'Save preferences'}
        </button>
        <button className="btn ghost" onClick={onDone} disabled={busy}>
          Back to the doors
        </button>
      </div>

      <p className="note">
        Every email carries a one-click unsubscribe, honoured the moment you tap it. No open
        tracking, no reminders, no change in how often we write.
      </p>
    </div>
  );
}
