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

// → { seeds: [{label, type}] }
export function generateSeeds({ count = 4, exclude = [] } = {}) {
  return generate('/api/seeds', { count, exclude });
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

// prefs: {enabled, topics: [], wildcard, sendHour, frequency}
export function putEmailPrefs(p) {
  return request('/api/email-prefs', { method: 'PUT', body: p });
}
