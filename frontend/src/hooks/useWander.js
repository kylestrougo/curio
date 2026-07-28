import { useState, useEffect, useRef } from 'react';
import * as api from '../api.js';
import { SEED_POOL, pickSeeds } from '../seedPool.js';

// ─────────────────────────────────────────────────────────────
// The engine: the trail, the tree, the seed pool, and every call that
// feeds them. Ported wholesale from the prototype, with two additions —
// the backend does the generating, and when someone is signed in the
// wander is mirrored to the server as it happens.
//
// Persistence is strictly a side effect. Every call is fire-and-forget:
// if the server is down, the wander carries on exactly as it does for a
// signed-out visitor.
// ─────────────────────────────────────────────────────────────

// Persistence never breaks the wander. It only ever leaves a note.
function shrug(what, e) {
  console.warn(`[curio] ${what} didn't persist:`, e && e.message ? e.message : e);
}

export function useWander(user) {
  const signedIn = !!(user && user.id != null);

  const [view, setView] = useState('home'); // home | page | saved | map | recap | auth | settings | admin
  const [trail, setTrail] = useState([]); // current linear path (page objects)
  const [seeds, setSeeds] = useState(() => pickSeeds()); // instant first paint
  const [saved, setSaved] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [ask, setAsk] = useState('');
  const [followQ, setFollowQ] = useState('');
  const [moreLoading, setMoreLoading] = useState(false);
  const [qaLoading, setQaLoading] = useState(false);
  const [recap, setRecap] = useState(null); // {path, synthesis, thread} | "loading" | {failed:msg}
  const [resumeHint, setResumeHint] = useState(null); // {wander, door} — shown once, quietly

  const scrollRef = useRef(null);
  const reqId = useRef(0); // ignore stale in-flight responses
  const didInit = useRef(false); // StrictMode double-mount guard
  const poolRef = useRef([...SEED_POOL]); // grows as the backend restocks it
  const seenRef = useRef(new Set()); // doors already dealt this session
  const refillingRef = useRef(false); // one restock call at a time
  const idRef = useRef(0); // unique ids for tree nodes
  const visitedRef = useRef([]); // every page opened this wander, with parent links — the tree
  const seedsRef = useRef(seeds); // seeds read from inside async callbacks
  seedsRef.current = seeds;

  // ── server mirror ──────────────────────────────────────────
  const wanderIdRef = useRef(null); // server id of the wander in progress
  const wanderPromiseRef = useRef(null); // in-flight create, so we only make one
  const serverIdsRef = useRef(new Map()); // nodeId → Promise<serverId | null>

  const current = trail[trail.length - 1] || null;

  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    loadSeeds();
    const token = new URLSearchParams(window.location.search).get('door');
    if (token) openDoorToken(token);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTo(0, 0);
  }, [view, trail.length]);

  // Signing in pulls down the durable half: saved pages, and the quiet
  // "you left off at ___". Signing out puts the screen back to anonymous.
  useEffect(() => {
    if (user === undefined) return; // auth still unknown

    if (!signedIn) {
      setSaved([]);
      setResumeHint(null);
      wanderIdRef.current = null;
      wanderPromiseRef.current = null;
      serverIdsRef.current = new Map();
      return;
    }

    let live = true;
    api
      .listSaves()
      .then((r) => {
        if (!live) return;
        const fromServer = (r.saves || []).map((p) => ({
          ...p,
          serverId: p.id,
          more: p.more || [],
          qa: p.qa || [],
          buttons: p.buttons || [],
        }));
        // Anything saved before signing in stays put, at the top.
        setSaved((local) => {
          const have = new Set(fromServer.map((p) => p.title));
          return [...local.filter((p) => !have.has(p.title)), ...fromServer];
        });
      })
      .catch((e) => shrug('saved pages', e));

    api
      .resume()
      .then((r) => {
        if (!live) return;
        if (r && (r.wander || r.door)) setResumeHint(r);
      })
      .catch((e) => shrug('resume', e));

    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, signedIn]);

  // ── server mirror helpers ──────────────────────────────────

  function ensureWander() {
    if (!signedIn) return Promise.resolve(null);
    if (wanderIdRef.current != null) return Promise.resolve(wanderIdRef.current);
    if (!wanderPromiseRef.current) {
      wanderPromiseRef.current = api
        .createWander()
        .then((r) => {
          wanderIdRef.current = r.id;
          return r.id;
        })
        .catch((e) => {
          shrug('new wander', e);
          wanderPromiseRef.current = null;
          return null;
        });
    }
    return wanderPromiseRef.current;
  }

  function attachServerId(nodeId, serverId) {
    const vi = visitedRef.current.findIndex((n) => n.nodeId === nodeId);
    if (vi >= 0) visitedRef.current[vi] = { ...visitedRef.current[vi], serverId };
    setTrail((t) => t.map((p) => (p.nodeId === nodeId ? { ...p, serverId } : p)));
  }

  function persistPage(page) {
    if (!signedIn) return;
    const p = ensureWander()
      .then((wid) => {
        if (wid == null) return null;
        return api
          .appendPage(wid, {
            clientNodeId: page.nodeId,
            parentClientNodeId: page.parentId,
            kind: page.kind,
            title: page.title,
            blurb: page.blurb,
            buttons: page.buttons,
          })
          .then((r) => {
            attachServerId(page.nodeId, r.id);
            return r.id;
          });
      })
      .catch((e) => {
        shrug('page', e);
        return null;
      });
    serverIdsRef.current.set(page.nodeId, p);
  }

  // The append may still be in flight when someone hits "Tell me more".
  function resolveServerId(nodeId) {
    const pending = serverIdsRef.current.get(nodeId);
    if (pending) return pending;
    const node = visitedRef.current.find((n) => n.nodeId === nodeId);
    return Promise.resolve(node && node.serverId != null ? node.serverId : null);
  }

  function persistPatch(nodeId, patch) {
    if (!signedIn) return;
    resolveServerId(nodeId)
      .then((id) => (id == null ? null : api.patchPage(id, patch)))
      .catch((e) => shrug('page detail', e));
  }

  // ── seeds ──────────────────────────────────────────────────

  function addToPool(newSeeds) {
    const have = new Set(poolRef.current.map((s) => s.label));
    for (const s of newSeeds) {
      if (s && s.label && !have.has(s.label)) poolRef.current.push(s);
    }
  }

  async function loadSeeds() {
    // Background refresh: home is already showing pool seeds. Only swap in
    // fresh doors if the user hasn't started wandering.
    try {
      const onScreen = seedsRef.current.map((s) => s.label);
      const j = await api.generateSeeds({ count: 4, exclude: onScreen });
      if (j.seeds && j.seeds.length === 4) {
        addToPool(j.seeds);
        setSeeds(j.seeds); // fresh doors, fades in
      }
    } catch {
      /* keep pool seeds */
    }
  }

  // Quietly restock the pool with novel doors when the unseen supply runs low.
  async function maybeRefillPool() {
    const unseen = poolRef.current.filter((s) => !seenRef.current.has(s.label));
    if (unseen.length >= 8 || refillingRef.current) return;
    refillingRef.current = true;
    const recent = [...seenRef.current].slice(-20);
    try {
      const j = await api.generateSeeds({ count: 6, exclude: recent });
      if (j.seeds && j.seeds.length) addToPool(j.seeds);
    } catch {
      /* pool just cycles until the next attempt */
    } finally {
      refillingRef.current = false;
    }
  }

  function shuffleDoors() {
    // Instant: deal 4 unseen doors. If the session has exhausted the pool,
    // recycle the oldest rather than ever making the user wait.
    setSeeds((currentSeeds) => {
      for (const s of currentSeeds) seenRef.current.add(s.label);
      const onScreen = currentSeeds.map((s) => s.label);
      let fresh = pickSeeds(
        4,
        onScreen,
        poolRef.current.filter((s) => !seenRef.current.has(s.label))
      );
      if (fresh.length < 4) {
        seenRef.current = new Set(onScreen); // recycle: only avoid what's on screen
        fresh = [
          ...fresh,
          ...pickSeeds(4 - fresh.length, [...onScreen, ...fresh.map((s) => s.label)], poolRef.current),
        ];
      }
      return fresh;
    });
    maybeRefillPool();
  }

  // ── the core tap ───────────────────────────────────────────

  async function openPage(label, type, resetTo = null, surprise = false) {
    const myReq = ++reqId.current;
    setLoading(true);
    setError(null);
    clearPageExtras();
    setResumeHint(null); // shown once; opening any door retires it
    setView('page');
    // Last 4 steps are enough context; unbounded history slows every deep tap.
    const priorTitles = (resetTo !== null ? [] : trail).map((p) => p.title).slice(-4);
    // Tree bookkeeping: capture the parent before the await.
    const parentId = resetTo !== null ? null : current ? current.nodeId : null;
    const exclude = surprise
      ? [...visitedRef.current.slice(-12).map((n) => n.title), ...seedsRef.current.map((s) => s.label)]
      : [];
    try {
      const j = await api.generatePage({
        label: surprise ? null : label,
        kind: type,
        path: priorTitles,
        surprise,
        exclude,
      });
      if (myReq !== reqId.current) return; // user navigated away — drop stale result
      const page = {
        nodeId: ++idRef.current,
        parentId,
        kind: type,
        title: j.title || label || 'Somewhere unexpected',
        blurb: j.blurb || '',
        buttons: (j.buttons || []).slice(0, 5),
      };
      visitedRef.current.push(page);
      setTrail((t) => (resetTo !== null ? [page] : [...t, page]));
      persistPage(page);
    } catch (e) {
      if (myReq !== reqId.current) return;
      setError({ label, type, resetTo, surprise, quota: !!e.quota, message: e.message });
    } finally {
      if (myReq === reqId.current) setLoading(false);
    }
  }

  function clearPageExtras() {
    setFollowQ('');
    setMoreLoading(false);
    setQaLoading(false);
  }

  function goToCrumb(i) {
    reqId.current++; // cancel any in-flight page
    setLoading(false);
    setError(null);
    clearPageExtras();
    if (i < 0) {
      setView('home');
      return;
    }
    setTrail((t) => t.slice(0, i + 1));
    setView('page');
  }

  function openSaved(p) {
    // Show the exact page that was saved — no refetch, no API call.
    reqId.current++;
    setLoading(false);
    setError(null);
    clearPageExtras();
    const page = { ...p, nodeId: ++idRef.current, parentId: null };
    visitedRef.current.push(page);
    setTrail([page]);
    setView('page');
  }

  // Jump anywhere in the tree: rebuild the linear trail from root to that node.
  function jumpToNode(n) {
    reqId.current++;
    setLoading(false);
    setError(null);
    clearPageExtras();
    const byId = new Map(visitedRef.current.map((x) => [x.nodeId, x]));
    const path = [];
    let cur = n;
    while (cur) {
      path.unshift(cur);
      cur = cur.parentId != null ? byId.get(cur.parentId) : null;
    }
    setTrail(path);
    setView('page');
  }

  // Update the current page in place, but only if the user hasn't navigated away.
  function patchPage(idx, title, patch) {
    setTrail((t) => {
      if (!(t[idx] && t[idx].title === title)) return t;
      const updated = { ...t[idx], ...patch(t[idx]) };
      const vi = visitedRef.current.findIndex((n) => n.nodeId === updated.nodeId);
      if (vi >= 0) visitedRef.current[vi] = updated; // keep the tree copy current
      return t.map((p, i) => (i === idx ? updated : p));
    });
  }

  async function tellMore() {
    if (!current || moreLoading) return;
    const idx = trail.length - 1;
    const { nodeId, title, blurb, more = [], qa = [] } = current;
    setMoreLoading(true);
    try {
      const j = await api.generateMore({ title, said: [blurb, ...more].join(' ') });
      if (j.more) {
        patchPage(idx, title, (p) => ({ more: [...(p.more || []), j.more] }));
        persistPatch(nodeId, { more: [...more, j.more], qa });
      }
    } catch {
      /* leave page as-is; button simply stops loading */
    } finally {
      setMoreLoading(false);
    }
  }

  async function askFollowUp() {
    const q = followQ.trim();
    if (!q || !current || qaLoading) return;
    const idx = trail.length - 1;
    const { nodeId, title, blurb, more = [], qa = [] } = current;
    setFollowQ('');
    setQaLoading(true);
    try {
      const j = await api.generateAsk({ title, said: [blurb, ...more].join(' '), question: q });
      if (j.answer) {
        patchPage(idx, title, (p) => ({ qa: [...(p.qa || []), { q, a: j.answer }] }));
        persistPatch(nodeId, { more, qa: [...qa, { q, a: j.answer }] });
      }
    } catch (e) {
      const a = e.quota ? e.message : "That one didn't come through — try asking again.";
      patchPage(idx, title, (p) => ({ qa: [...(p.qa || []), { q, a }] }));
    } finally {
      setQaLoading(false);
    }
  }

  // ── Closing the wander ─────────────────────────────────────
  // The user decides when they're done: a quiet "Close the wander" appears
  // once they've walked 3+ pages. No timers, no nudges.
  async function closeWander() {
    const path = visitedRef.current.map((n) => n.title);
    reqId.current++; // cancel any in-flight page
    setLoading(false);
    setError(null);
    clearPageExtras();
    setRecap('loading');
    setView('recap');
    try {
      const j = await api.generateRecap({ path });
      const done = { path, synthesis: j.synthesis || '', thread: j.thread || '' };
      setRecap(done);
      if (signedIn && wanderIdRef.current != null) {
        api.closeWander(wanderIdRef.current, done).catch((e) => shrug('recap', e));
      }
    } catch (e) {
      setRecap({ failed: e.quota ? e.message : "Couldn't close the book." });
    }
  }

  function keepWandering() {
    setRecap(null);
    setView(trail.length ? 'page' : 'home');
  }

  function startFresh() {
    reqId.current++;
    visitedRef.current = [];
    setRecap(null);
    setTrail([]);
    setError(null);
    clearPageExtras();
    setView('home');
    // A closed wander is finished on the server too; the next page starts a new one.
    wanderIdRef.current = null;
    wanderPromiseRef.current = null;
    serverIdsRef.current = new Map();
    shuffleDoors(); // fresh hand of doors for the new wander
  }

  function toggleSave() {
    if (!current) return;
    const already = saved.find((p) => p.title === current.title);
    setSaved((s) =>
      already ? s.filter((p) => p.title !== current.title) : [{ ...current }, ...s]
    );
    if (!signedIn) return;
    if (already) {
      const sid = already.serverId != null ? already.serverId : already.id;
      if (sid != null) api.removeSave(sid).catch((e) => shrug('unsave', e));
      return;
    }
    const title = current.title;
    resolveServerId(current.nodeId)
      .then((id) => {
        if (id == null) return null;
        setSaved((s) => s.map((p) => (p.title === title ? { ...p, serverId: id } : p)));
        return api.addSave(id);
      })
      .catch((e) => shrug('save', e));
  }

  function submitAsk() {
    const q = ask.trim();
    if (!q) return;
    setAsk('');
    openPage(q, 'topic');
  }

  // ── the return hook ────────────────────────────────────────
  // Pick a wander back up exactly where it was left — tree, map and all.
  async function resumeWander(id) {
    const myReq = ++reqId.current;
    setLoading(true);
    setError(null);
    clearPageExtras();
    setResumeHint(null);
    setView('page');
    try {
      const r = await api.getWander(id);
      if (myReq !== reqId.current) return;
      const pages = r.pages || [];
      if (!pages.length) {
        setView('home');
        return;
      }
      const nodes = pages.map((p) => ({
        nodeId: p.clientNodeId != null ? p.clientNodeId : p.id,
        parentId: p.parentClientNodeId != null ? p.parentClientNodeId : null,
        serverId: p.id,
        kind: p.kind,
        title: p.title,
        blurb: p.blurb,
        more: p.more || [],
        qa: p.qa || [],
        buttons: p.buttons || [],
      }));
      idRef.current = nodes.reduce((m, n) => Math.max(m, n.nodeId || 0), idRef.current);
      visitedRef.current = nodes;
      wanderIdRef.current = r.id != null ? r.id : id;
      wanderPromiseRef.current = null;
      serverIdsRef.current = new Map();
      const byId = new Map(nodes.map((n) => [n.nodeId, n]));
      const path = [];
      let cur = nodes[nodes.length - 1];
      while (cur) {
        path.unshift(cur);
        cur = cur.parentId != null ? byId.get(cur.parentId) : null;
      }
      setTrail(path);
    } catch (e) {
      if (myReq !== reqId.current) return;
      shrug('reopening the wander', e);
      setView('home');
    } finally {
      if (myReq === reqId.current) setLoading(false);
    }
  }

  function dismissResume() {
    setResumeHint(null);
  }

  // An email door: /d/:token lands here as /?door=:token. Exchange the token
  // for the door and walk through it. A stale token just leaves you at home.
  async function openDoorToken(token) {
    const myReq = ++reqId.current;
    setLoading(true);
    setError(null);
    setView('page');
    try {
      window.history.replaceState({}, '', window.location.pathname);
    } catch {
      /* the token is single-use anyway */
    }
    try {
      const d = await api.getDoor(token);
      if (myReq !== reqId.current) return;
      if (!d || !d.label) {
        setLoading(false);
        setView('home');
        return;
      }
      openPage(d.label, d.type || 'topic', true);
    } catch (e) {
      if (myReq !== reqId.current) return;
      shrug('door link', e);
      setLoading(false);
      setView('home');
    }
  }

  const isSaved = !!(current && saved.some((p) => p.title === current.title));

  return {
    // state
    view,
    setView,
    trail,
    current,
    seeds,
    saved,
    isSaved,
    loading,
    error,
    ask,
    setAsk,
    followQ,
    setFollowQ,
    moreLoading,
    qaLoading,
    recap,
    resumeHint,
    // refs the views read directly
    scrollRef,
    visitedRef,
    // actions
    shuffleDoors,
    openPage,
    goToCrumb,
    openSaved,
    jumpToNode,
    tellMore,
    askFollowUp,
    closeWander,
    keepWandering,
    startFresh,
    toggleSave,
    submitAsk,
    setRecap,
    resumeWander,
    dismissResume,
  };
}
