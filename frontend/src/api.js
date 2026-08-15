// ─────────────────────────────────────────────────────────────
// The one place Curio talks to its backend.
//
// The prototype called api.anthropic.com straight from the browser and did its
// own fence-stripping and brace-extraction on the reply. All of that now lives
// server-side: every endpoint here returns parsed JSON, already shaped.
// ─────────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    // The one failure worth its own words: the shared free-model quota.
    this.quota = status === 429 || code === 'quota';
  }
}

const QUOTA_MESSAGE =
  "That's the day's generating spent — the free models take the night off. " +
  'Your trail is still here whenever you come back.';

function fallbackMessage(status, code) {
  if (status === 429 || code === 'quota') return QUOTA_MESSAGE;
  if (status === 401) return 'You need to be signed in for that.';
  if (status === 403) return "That isn't yours to open.";
  if (status === 404) return "There's nothing at that address.";
  if (status === 0) return "The connection didn't hold.";
  return "Something on our side didn't cooperate.";
}

async function request(path, { method = 'GET', body } = {}) {
  let res;
  try {
    res = await fetch(path, {
      method,
      credentials: 'include',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, 'network', fallbackMessage(0, 'network'));
  }

  let data = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }

  if (!res.ok) {
    const code = (data && data.error) || `http_${res.status}`;
    const message = (data && data.message) || fallbackMessage(res.status, code);
    throw new ApiError(res.status, code, message);
  }
  return data === null ? {} : data;
}

// Generation is the slow, flaky path: free models rate-limit and hiccup. The
// prototype took one quiet retry before surfacing anything; keep that, but never
// retry a quota — a second ask can't buy back a spent daily cap — and never
// retry `generation_failed`, which already means the whole server-side model
// chain was walked. One LLM call per tap stays law.
async function generate(path, body) {
  try {
    return await request(path, { method: 'POST', body });
  } catch (e) {
    if (e instanceof ApiError && !e.quota && e.code !== 'generation_failed' && e.status >= 500) {
      await new Promise((r) => setTimeout(r, 2000));
      return request(path, { method: 'POST', body });
    }
    throw e;
  }
}

// ── Generation ───────────────────────────────────────────────

// ── streaming ────────────────────────────────────────────────
//
// more/ask can stream: they're single prose fields, so tokens go straight to
// the screen. The server only falls back between models BEFORE the first
// token; a mid-stream death arrives as an SSE error event, and callers are
// expected to retry the non-streaming endpoint (one fresh call, not a loop).

async function streamText(path, body, onChunk) {
  let res;
  try {
    res = await fetch(path, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, 'network', fallbackMessage(0, 'network'));
  }

  const ctype = res.headers.get('content-type') || '';
  if (!res.ok || !ctype.includes('text/event-stream') || !res.body) {
    // The gate and validation errors still arrive as ordinary JSON.
    let data = null;
    try {
      data = JSON.parse(await res.text());
    } catch {
      data = null;
    }
    const code = (data && data.error) || `http_${res.status}`;
    throw new ApiError(res.status, code, (data && data.message) || fallbackMessage(res.status, code));
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  let full = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let sep;
    while ((sep = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, sep);
      buf = buf.slice(sep + 2);
      let event = 'message';
      let dataStr = '';
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) dataStr += line.slice(5).trim();
      }
      if (event === 'done') {
        // more/ask send an empty done; page's done carries the finished page.
        let payload = null;
        try {
          payload = dataStr ? JSON.parse(dataStr) : null;
        } catch {
          payload = null;
        }
        return { full, done: payload };
      }
      if (event === 'error') {
        throw new ApiError(502, 'stream_failed', dataStr ? JSON.parse(dataStr) : 'The stream broke off.');
      }
      if (dataStr) {
        const chunk = JSON.parse(dataStr);
        full += chunk;
        if (onChunk) onChunk(chunk, full);
      }
    }
  }
  // Connection closed without a done event — trust nothing partial.
  throw new ApiError(0, 'stream_failed', 'The stream broke off.');
}

// Streams tokens via onChunk and resolves with the full text; falls back to
// the JSON endpoint on any streaming failure (except quota — a second ask
// can't buy back a spent cap).
export async function streamMore({ title, said }, onChunk) {
  try {
    const r = await streamText('/api/more/stream', { title, said }, onChunk);
    return r.full;
  } catch (e) {
    if (e instanceof ApiError && e.quota) throw e;
    const j = await generateMore({ title, said });
    return j.more;
  }
}

export async function streamAsk({ title, said, question }, onChunk) {
  try {
    const r = await streamText('/api/ask/stream', { title, said, question }, onChunk);
    return r.full;
  } catch (e) {
    if (e instanceof ApiError && e.quota) throw e;
    const j = await generateAsk({ title, said, question });
    return j.answer;
  }
}

// Streaming door-open: onChunk receives blurb text as the model writes it;
// resolves with the finished page {title, blurb, buttons}. Falls back to the
// JSON endpoint on any stream failure except quota.
export async function streamPage(body, onChunk) {
  try {
    const r = await streamText('/api/page/stream', body, onChunk);
    if (r.done && r.done.title) return r.done;
    throw new ApiError(502, 'stream_failed', 'The page never finished.');
  } catch (e) {
    if (e instanceof ApiError && e.quota) throw e;
    return generatePage(body);
  }
}

// → { seeds: [{label, type}] }
export function generateSeeds({ count = 4, exclude = [] } = {}) {
  return generate('/api/seeds', { count, exclude });
}

// → { seeds: [{label, type}] } — anchored to the signed-in user's saved
// interests, which stay server-side; {seeds: []} when none are configured.
export function generateTopicalSeeds({ count = 6, exclude = [] } = {}) {
  return generate('/api/seeds/topical', { count, exclude });
}

// → { title, blurb, buttons: [{label, type}] }  (exactly 5 buttons)
export function generatePage({ label = null, kind = 'topic', path = [], surprise = false, exclude = [] } = {}) {
  return generate('/api/page', { label, kind, path, surprise, exclude });
}

// → { more }
export function generateMore({ title, said }) {
  return generate('/api/more', { title, said });
}

// → { answer }
export function generateAsk({ title, said, question }) {
  return generate('/api/ask', { title, said, question });
}

// → { synthesis, thread }
export function generateRecap({ path }) {
  return generate('/api/recap', { path });
}

// ── Auth ─────────────────────────────────────────────────────

// → { user } | { user: null } — never 401
export function me() {
  return request('/api/auth/me');
}

export function login({ email, password }) {
  return request('/api/auth/login', { method: 'POST', body: { email, password } });
}

export function signup({ email, password }) {
  return request('/api/auth/signup', { method: 'POST', body: { email, password } });
}

export function logout() {
  return request('/api/auth/logout', { method: 'POST', body: {} });
}

// ── Persistence (signed-in only) ─────────────────────────────

export function listWanders() {
  return request('/api/wanders');
}

export function getWander(id) {
  return request(`/api/wanders/${encodeURIComponent(id)}`);
}

export function createWander() {
  return request('/api/wanders', { method: 'POST', body: {} });
}

// page: {clientNodeId, parentClientNodeId, kind, title, blurb, buttons} → {id}
export function appendPage(wanderId, page) {
  return request(`/api/wanders/${encodeURIComponent(wanderId)}/pages`, { method: 'POST', body: page });
}

// patch: {more?: [...], qa?: [...]}
export function patchPage(pageId, patch) {
  return request(`/api/pages/${encodeURIComponent(pageId)}`, { method: 'PATCH', body: patch });
}

// recap: {path, synthesis, thread}
export function closeWander(id, recap) {
  return request(`/api/wanders/${encodeURIComponent(id)}/close`, { method: 'POST', body: { recap } });
}

export function listSaves() {
  return request('/api/saves');
}

export function addSave(pageId) {
  return request('/api/saves', { method: 'POST', body: { pageId } });
}

export function removeSave(pageId) {
  return request(`/api/saves/${encodeURIComponent(pageId)}`, { method: 'DELETE' });
}

// → { wander: {id, lastTitle, pageCount} | null, door: {label, type} | null }
export function resume() {
  return request('/api/resume');
}

// Email deep link: /d/:token redirects to /?door=:token, and this exchanges
// that token for the door itself. → { label, type }
export function getDoor(token) {
  return request(`/api/door/${encodeURIComponent(token)}`);
}

// Snapshot share: freeze the current page, get a token for /s/:token. → { token, url }
export function createShare(page) {
  return request('/api/share', { method: 'POST', body: page });
}

// → { title, blurb, kind, more, qa, buttons, terms } — public, no login needed.
export function getShare(token) {
  return request(`/api/share/${encodeURIComponent(token)}`);
}

// ── Admin ────────────────────────────────────────────────────

export function adminModels() {
  return request('/api/admin/models');
}

export function adminConfig() {
  return request('/api/admin/config');
}

export function saveAdminConfig(cfg) {
  return request('/api/admin/config', { method: 'PUT', body: cfg });
}

// → { ok, raw, parsed, latencyMs, error }
export function adminTest({ model, intent }) {
  return request('/api/admin/test', { method: 'POST', body: { model, intent } });
}

export function adminStats() {
  return request('/api/admin/stats');
}

// ── Email ────────────────────────────────────────────────────

export function getEmailPrefs() {
  return request('/api/email-prefs');
}

// prefs: {enabled, topics: [], wildcard, sendHour, frequency, timezone}
// timezone is the browser's IANA zone — sendHour is on the user's clock.
export function putEmailPrefs(p) {
  return request('/api/email-prefs', { method: 'PUT', body: p });
}
