import React, { useState, useEffect, useRef } from "react";

// ─────────────────────────────────────────────────────────────
// Curio — a curiosity engine (MVP)
// Tap a door → land on a page → tap where curiosity pulls → repeat.
// Claude generates every page live, seeded with your path so far.
// ─────────────────────────────────────────────────────────────

const STYLE = `
@import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;1,9..144,400&family=Newsreader:ital,opsz@0,6..72;1,6..72&family=Inter:wght@400;500;600&display=swap');

.curio-root{
  --paper:#F4F2EB; --card:#FBFAF6; --ink:#1C2B3A; --ink-soft:#4A5A68;
  --brass:#A9781F; --slate:#3E5C76; --green:#55704E;
  --line:rgba(28,43,58,0.13);
  background:var(--paper); color:var(--ink);
  font-family:'Newsreader',Georgia,serif;
  min-height:100vh; width:100%;
  -webkit-font-smoothing:antialiased;
}
.curio-root *{box-sizing:border-box;}
.wrap{max-width:640px; margin:0 auto; padding:0 20px 96px;}

/* header + trail */
.top{position:sticky; top:0; z-index:5; background:linear-gradient(var(--paper) 78%, rgba(244,242,235,0));
  padding:18px 0 10px; margin:0 -20px; padding-left:20px; padding-right:20px;}
.brandrow{display:flex; align-items:center; justify-content:space-between;}
.brand{display:flex; align-items:center; gap:9px; cursor:pointer; user-select:none;}
.mark{width:16px; height:22px; border:1.5px solid var(--ink); border-radius:2px 8px 8px 2px; position:relative;}
.mark::after{content:""; position:absolute; right:3px; top:9px; width:3px; height:3px; border-radius:50%; background:var(--brass);}
.brand h1{font-family:'Fraunces',serif; font-weight:600; font-size:20px; letter-spacing:.2px; margin:0;}
.saved-btn{font-family:'Inter',sans-serif; font-size:12.5px; font-weight:500; letter-spacing:.3px;
  color:var(--ink-soft); background:none; border:1px solid var(--line); border-radius:999px;
  padding:6px 13px; cursor:pointer; transition:all .15s;}
.saved-btn:hover{border-color:var(--ink); color:var(--ink);}
.saved-btn b{color:var(--brass); font-weight:600;}

.trail{display:flex; gap:4px; align-items:center; overflow-x:auto; margin-top:12px;
  font-family:'Inter',sans-serif; font-size:12px; scrollbar-width:none; padding-bottom:2px;}
.trail::-webkit-scrollbar{display:none;}
.crumb{white-space:nowrap; color:var(--ink-soft); background:none; border:none; cursor:pointer;
  padding:2px 2px; transition:color .15s;}
.crumb:hover{color:var(--ink);}
.crumb.here{color:var(--ink); font-weight:600;}
.sep{color:var(--line); font-size:11px;}

/* home */
.home{padding-top:34px; animation:fade .4s ease both;}
.home .ey{font-family:'Inter',sans-serif; font-size:11.5px; letter-spacing:2px; text-transform:uppercase; color:var(--brass); font-weight:600;}
.home h2{font-family:'Fraunces',serif; font-weight:400; font-size:33px; line-height:1.12; margin:12px 0 10px;}
.home h2 i{font-style:italic;}
.home p.lede{font-size:17px; line-height:1.5; color:var(--ink-soft); margin:0 0 26px; max-width:30em;}
.doors-label{font-family:'Inter',sans-serif; font-size:11.5px; letter-spacing:1.5px; text-transform:uppercase; color:var(--ink-soft); margin:0 0 12px;}
.doors-row{display:flex; align-items:center; justify-content:space-between; margin:0 0 12px;}
.shuffle{font-family:'Inter',sans-serif; font-size:12.5px; font-weight:500; letter-spacing:.3px;
  display:inline-flex; align-items:center; gap:6px; color:var(--ink-soft);
  background:none; border:1px solid var(--line); border-radius:999px; padding:5px 12px;
  cursor:pointer; transition:all .15s;}
.shuffle:hover{border-color:var(--brass); color:var(--ink);}
.shuffle svg{width:13px; height:13px;}

/* page */
.page{padding-top:26px; animation:fade .35s ease both;}
.page h2{font-family:'Fraunces',serif; font-weight:600; font-size:30px; line-height:1.15; margin:0 0 14px; letter-spacing:.1px;}
.blurb{font-size:18.5px; line-height:1.6; margin:0 0 22px;}
.blurb.deeper{margin-top:-6px; animation:fade .35s ease both;}

/* follow-up Q&A */
.qa-list{margin:0 0 14px; border-left:2px solid var(--line); padding-left:16px;}
.qa{margin:0 0 16px; animation:fade .35s ease both;}
.qa .q{font-family:'Inter',sans-serif; font-size:13px; font-weight:600; color:var(--brass);
  letter-spacing:.2px; margin:0 0 5px;}
.qa .a{font-size:16.5px; line-height:1.55; margin:0;}
.save-row{display:flex; align-items:center; gap:12px; margin-bottom:30px;}
.save{font-family:'Inter',sans-serif; font-size:13px; font-weight:500; cursor:pointer;
  display:inline-flex; align-items:center; gap:7px; padding:8px 15px; border-radius:999px;
  background:none; border:1px solid var(--line); color:var(--ink-soft); transition:all .16s;}
.save:hover{border-color:var(--brass); color:var(--ink);}
.save.on{background:var(--brass); border-color:var(--brass); color:#FBFAF6;}
.save svg{width:14px; height:14px;}

.next-label{font-family:'Inter',sans-serif; font-size:11.5px; letter-spacing:1.5px; text-transform:uppercase; color:var(--ink-soft); margin:0 0 13px;}

/* buttons */
.doors{display:flex; flex-direction:column; gap:10px; animation:fade .4s ease both;}
.door{position:relative; text-align:left; width:100%; cursor:pointer;
  background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:15px 16px 15px 18px; transition:transform .14s ease, border-color .16s, box-shadow .16s;
  display:flex; flex-direction:column; gap:5px; overflow:hidden;}
.door::before{content:""; position:absolute; left:0; top:0; bottom:0; width:4px; background:var(--slate);}
.door.fact::before{background:var(--slate);}
.door.question::before{background:var(--brass);}
.door.topic::before{background:var(--green);}
.door:hover{transform:translateY(-1px); border-color:var(--ink); box-shadow:0 6px 18px -12px rgba(28,43,58,.4);}
.door:focus-visible{outline:2px solid var(--ink); outline-offset:2px;}
.door .kind{font-family:'Inter',sans-serif; font-size:10.5px; letter-spacing:1.4px; text-transform:uppercase; font-weight:600;}
.door.fact .kind{color:var(--slate);}
.door.question .kind{color:var(--brass);}
.door.topic .kind{color:var(--green);}
.door .lbl{font-size:17.5px; line-height:1.35; color:var(--ink);}

/* ask box */
.ask{margin-top:16px; display:flex; gap:8px; align-items:center;
  border:1px dashed var(--line); border-radius:12px; padding:6px 6px 6px 15px; transition:border-color .16s;}
.ask:focus-within{border-color:var(--ink);}
.ask input{flex:1; border:none; background:none; font-family:'Newsreader',serif; font-size:16px; color:var(--ink); outline:none;}
.ask input::placeholder{color:var(--ink-soft); opacity:.75;}
.ask button{font-family:'Inter',sans-serif; font-size:13px; font-weight:500; cursor:pointer;
  border:none; background:var(--ink); color:var(--paper); border-radius:8px; padding:9px 14px; transition:opacity .15s;}
.ask button:disabled{opacity:.4; cursor:default;}

/* saved view */
.saved-view{padding-top:30px; animation:fade .35s ease both;}
.saved-view h2{font-family:'Fraunces',serif; font-weight:400; font-size:27px; margin:0 0 6px;}
.saved-view .sub{color:var(--ink-soft); font-size:15px; margin:0 0 24px;}
.saved-item{width:100%; text-align:left; cursor:pointer; background:var(--card);
  border:1px solid var(--line); border-radius:12px; padding:15px 16px; margin-bottom:10px; transition:all .15s;}
.saved-item:hover{border-color:var(--brass);}
.saved-item .t{font-family:'Fraunces',serif; font-size:18px; margin:0 0 4px;}
.saved-item .b{font-size:14.5px; color:var(--ink-soft); line-height:1.45; margin:0;
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;}
.empty{color:var(--ink-soft); font-size:16px; line-height:1.6; padding:8px 0;}

/* states */
.loading{display:flex; align-items:center; gap:12px; color:var(--ink-soft); font-size:16px; padding:38px 2px; animation:fade .3s both;}
.dots{display:inline-flex; gap:5px;}
.dots i{width:6px; height:6px; border-radius:50%; background:var(--brass); animation:blink 1.1s infinite ease-in-out;}
.dots i:nth-child(2){animation-delay:.18s;} .dots i:nth-child(3){animation-delay:.36s;}
.errline{color:var(--ink); font-size:16px; padding:30px 2px;}
.errline button{font-family:'Inter',sans-serif; font-size:13px; margin-left:6px; background:none; border:1px solid var(--ink);
  border-radius:999px; padding:5px 12px; cursor:pointer; color:var(--ink);}

.foot{font-family:'Inter',sans-serif; font-size:11px; color:var(--ink-soft); opacity:.7;
  text-align:center; margin-top:40px; letter-spacing:.2px;}

/* wildcard door */
.door.wild{border-style:dashed;}
.door.wild::before{background:linear-gradient(var(--brass), var(--green));}
.door.wild .kind{color:var(--brass);}

/* closing the wander */
.close-row{text-align:center; margin-top:40px;}
.close-wander{font-family:'Inter',sans-serif; font-size:12.5px; font-weight:500; letter-spacing:.4px;
  color:var(--ink-soft); background:none; border:1px solid var(--line); border-radius:999px;
  padding:7px 16px; cursor:pointer; transition:all .15s;}
.close-wander:hover{border-color:var(--brass); color:var(--ink);}
.close-row .foot{margin-top:12px;}

/* map — the explored territory */
.map-view{padding-top:30px; animation:fade .35s ease both;}
.map-view h2{font-family:'Fraunces',serif; font-weight:400; font-size:27px; margin:0 0 6px;}
.map-view .sub{color:var(--ink-soft); font-size:15px; margin:0 0 22px;}
.tbranch .tbranch{margin-left:9px; border-left:1px solid var(--line); padding-left:14px;}
.tnode{display:flex; align-items:baseline; gap:9px; width:100%; text-align:left;
  background:none; border:none; cursor:pointer; padding:6px 2px;
  font-family:'Newsreader',serif; font-size:17px; line-height:1.35; color:var(--ink-soft);
  transition:color .15s;}
.tnode:hover{color:var(--ink);}
.tnode.here{color:var(--ink); font-weight:600;}
.tnode.here .tlbl::after{content:" — you are here"; font-family:'Inter',sans-serif;
  font-size:11px; font-weight:500; letter-spacing:.5px; color:var(--brass);}
.tdot{width:7px; height:7px; border-radius:50%; flex:none; background:var(--green); transform:translateY(-1px);}
.tdot.fact{background:var(--slate);} .tdot.question{background:var(--brass);} .tdot.topic{background:var(--green);}

/* recap — colophon */
.recap{padding-top:34px; animation:fade .4s ease both;}
.recap .ey{font-family:'Inter',sans-serif; font-size:11.5px; letter-spacing:2px; text-transform:uppercase; color:var(--brass); font-weight:600; margin-bottom:16px;}
.recap-path{font-family:'Inter',sans-serif; font-size:12.5px; line-height:1.9; color:var(--ink-soft); margin:0 0 20px;}
.recap-path .sep{color:var(--brass);}
.recap-synth{font-family:'Fraunces',serif; font-size:22px; line-height:1.45; margin:0 0 26px;}
.recap-thread{border-top:1px solid var(--line); padding-top:18px; margin-bottom:30px;}
.recap-thread .tlabel{display:block; font-family:'Inter',sans-serif; font-size:11px; letter-spacing:1.5px; text-transform:uppercase; color:var(--ink-soft); margin-bottom:8px;}
.thread-q{font-family:'Newsreader',serif; font-style:italic; font-size:18px; line-height:1.4; color:var(--ink);
  background:none; border:none; padding:0; cursor:pointer; text-align:left; text-decoration:underline;
  text-decoration-color:var(--brass); text-underline-offset:4px; transition:opacity .15s;}
.thread-q:hover{opacity:.75;}
.recap-actions{display:flex; gap:10px;}

@keyframes fade{from{opacity:0; transform:translateY(6px);} to{opacity:1; transform:none;}}
@keyframes blink{0%,80%,100%{opacity:.25; transform:scale(.85);} 40%{opacity:1; transform:scale(1);}}
@media (prefers-reduced-motion:reduce){
  .home,.page,.saved-view,.loading{animation:none;}
  .door:hover{transform:none;}
  .dots i{animation:none; opacity:.7;}
}
`;

// Local seed pool — home renders instantly from these; fresh doors swap in
// quietly if the background call returns before the user starts wandering.
const SEED_POOL = [
  { label: "Why do we dream?", type: "question" },
  { label: "The library that mapped the ancient world", type: "topic" },
  { label: "Octopuses have three hearts", type: "fact" },
  { label: "How does a single idea become a whole language?", type: "question" },
  { label: "Honey never spoils", type: "fact" },
  { label: "The sound of a dying star", type: "topic" },
  { label: "Why is the ocean salty but rain isn't?", type: "question" },
  { label: "Rome's concrete outlasted ours — why?", type: "question" },
  { label: "The woman who mapped the ocean floor", type: "topic" },
  { label: "Sharks are older than trees", type: "fact" },
  { label: "How do cities decide where streets go?", type: "question" },
  { label: "The color that used to be poisonous", type: "topic" },
  { label: "Your body replaces itself — mostly", type: "fact" },
  { label: "What did silence sound like before machines?", type: "question" },
  { label: "The great emu war of 1932", type: "topic" },
  { label: "Bananas are berries; strawberries aren't", type: "fact" },
  { label: "Why do we find things beautiful?", type: "question" },
  { label: "The last common language of the Silk Road", type: "topic" },
  { label: "Lightning strikes Earth 8 million times a day", type: "fact" },
  { label: "Could you patent a color?", type: "question" },
];

function pickSeeds(n = 4, exclude = [], source = SEED_POOL) {
  const pool = source.filter((s) => !exclude.includes(s.label));
  const out = [];
  while (out.length < n && pool.length) {
    out.push(pool.splice(Math.floor(Math.random() * pool.length), 1)[0]);
  }
  return out;
}

const KIND_WORD = { fact: "Fact", question: "Question", topic: "Path" };

export default function Curio() {
  const [view, setView] = useState("home"); // home | page | saved | map | recap
  const [trail, setTrail] = useState([]); // current linear path (page objects)
  const [seeds, setSeeds] = useState(() => pickSeeds()); // instant first paint
  const [saved, setSaved] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [ask, setAsk] = useState("");
  const [followQ, setFollowQ] = useState("");
  const [moreLoading, setMoreLoading] = useState(false);
  const [qaLoading, setQaLoading] = useState(false);
  const scrollRef = useRef(null);
  const reqId = useRef(0);       // ignore stale in-flight responses
  const didInit = useRef(false);  // StrictMode double-mount guard
  const poolRef = useRef([...SEED_POOL]); // grows as Claude restocks it
  const seenRef = useRef(new Set());      // doors already dealt this session
  const refillingRef = useRef(false);     // one restock call at a time
  const idRef = useRef(0);                // unique ids for tree nodes
  const visitedRef = useRef([]);          // every page opened this wander, with parent links — the tree
  const [recap, setRecap] = useState(null); // {path, synthesis, thread} | "loading" | "error"

  const current = trail[trail.length - 1] || null;

  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    loadSeeds();
  }, []);
  useEffect(() => { if (scrollRef.current) scrollRef.current.scrollTo(0, 0); }, [view, trail.length]);

  async function callClaude(system, user, retried = false) {
    const res = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "claude-sonnet-4-6",
        max_tokens: 1000,
        system,
        messages: [{ role: "user", content: user }],
      }),
    });
    if (!res.ok) {
      // One quiet retry on rate-limit / server hiccup before surfacing an error.
      if (!retried && (res.status === 429 || res.status >= 500)) {
        await new Promise((r) => setTimeout(r, 2000));
        return callClaude(system, user, true);
      }
      throw new Error(`API ${res.status}`);
    }
    const data = await res.json();
    const text = (data.content || [])
      .filter((b) => b.type === "text").map((b) => b.text).join("");
    const clean = text.replace(/```json/gi, "").replace(/```/g, "").trim();
    const start = clean.indexOf("{");
    const end = clean.lastIndexOf("}");
    return JSON.parse(clean.slice(start, end + 1));
  }

  const PERSONA =
    "You are Curio, the knowledge engine behind a curiosity app. The user explores by tapping. " +
    "You are accurate and never invent facts. You write for a curious, intelligent adult and prize the genuinely " +
    "fascinating over the obvious.";

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
      const j = await callClaude(
        PERSONA +
          " Produce 4 irresistible entry points into knowledge, each from a very different domain (e.g. science, " +
          "history, art, technology, everyday life). Respond with ONLY JSON, no markdown: " +
          '{"seeds":[{"label": short enticing text max 8 words, "type": "fact"|"question"|"topic"}]}',
        "Give me today's four doors."
      );
      if (j.seeds && j.seeds.length === 4) {
        addToPool(j.seeds);
        setSeeds(j.seeds); // fresh doors, fades in
      }
    } catch (e) {
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
      const j = await callClaude(
        PERSONA +
          " Produce 6 irresistible entry points into knowledge across very different domains. " +
          "Avoid anything close to the excluded list. Respond with ONLY JSON, no markdown: " +
          '{"seeds":[{"label": short enticing text max 8 words, "type": "fact"|"question"|"topic"}]}',
        `Excluded (already shown): ${recent.join(" | ") || "none"}.\nGive me six new doors.`
      );
      if (j.seeds && j.seeds.length) addToPool(j.seeds);
    } catch (e) {
      /* pool just cycles until the next attempt */
    } finally {
      refillingRef.current = false;
    }
  }

  function shuffleDoors() {
    // Instant: deal 4 unseen doors. If the session has exhausted the pool,
    // recycle the oldest rather than ever making the user wait.
    setSeeds((current) => {
      for (const s of current) seenRef.current.add(s.label);
      const onScreen = current.map((s) => s.label);
      let fresh = pickSeeds(4, onScreen,
        poolRef.current.filter((s) => !seenRef.current.has(s.label)));
      if (fresh.length < 4) {
        seenRef.current = new Set(onScreen); // recycle: only avoid what's on screen
        fresh = [...fresh, ...pickSeeds(4 - fresh.length,
          [...onScreen, ...fresh.map((s) => s.label)], poolRef.current)];
      }
      return fresh;
    });
    maybeRefillPool();
  }

  async function openPage(label, type, resetTo = null, surprise = false) {
    const myReq = ++reqId.current;
    setLoading(true);
    setError(null);
    clearPageExtras();
    setView("page");
    // Last 4 steps are enough context; unbounded history slows every deep tap.
    const priorTitles = (resetTo !== null ? [] : trail).map((p) => p.title).slice(-4);
    const shape =
      ' Respond with ONLY JSON, no markdown, shaped exactly: ' +
      '{"title": string, "blurb": 2 vivid accurate sentences totaling under 45 words, ' +
      '"buttons":[{"label": short enticing text max 8 words, "type":"fact"|"question"|"topic"}]}. ' +
      "Return exactly 5 buttons that are a lively mix of surprising facts, provocative open questions, and " +
      "adjacent topics worth wandering into.";
    // Tree bookkeeping: capture the parent before the await.
    const parentId = resetTo !== null ? null : (current ? current.nodeId : null);
    try {
      const j = await callClaude(
        surprise
          ? PERSONA + shape +
            " Choose ONE genuinely delightful topic from a domain entirely absent from the excluded list — " +
            "something the user would never think to search for, but will be glad they found."
          : PERSONA + " For the item the user just tapped," + shape +
            " Do not repeat recent steps in the path.",
        surprise
          ? `Excluded territory: ${
              [...visitedRef.current.slice(-12).map((n) => n.title), ...seeds.map((s) => s.label)].join(" | ") || "none"
            }.\nSurprise me. Pick the topic and generate its page.`
          : `Recent path: ${priorTitles.join(" > ") || "start"}.\n` +
            `The user tapped: "${label}" (kind: ${type}).\nGenerate the page for "${label}".`
      );
      if (myReq !== reqId.current) return; // user navigated away — drop stale result
      const page = {
        nodeId: ++idRef.current,
        parentId,
        kind: type,
        title: j.title || label || "Somewhere unexpected",
        blurb: j.blurb || "",
        buttons: (j.buttons || []).slice(0, 5),
      };
      visitedRef.current.push(page);
      setTrail((t) => (resetTo !== null ? [page] : [...t, page]));
    } catch (e) {
      if (myReq !== reqId.current) return;
      setError({ label, type, resetTo, surprise });
    } finally {
      if (myReq === reqId.current) setLoading(false);
    }
  }

  function clearPageExtras() {
    setFollowQ("");
    setMoreLoading(false);
    setQaLoading(false);
  }

  function goToCrumb(i) {
    reqId.current++; // cancel any in-flight page
    setLoading(false);
    setError(null);
    clearPageExtras();
    if (i < 0) { setView("home"); return; }
    setTrail((t) => t.slice(0, i + 1));
    setView("page");
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
    setView("page");
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
    setView("page");
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
    const { title, blurb, more = [] } = current;
    setMoreLoading(true);
    try {
      const j = await callClaude(
        PERSONA +
          ' Respond with ONLY JSON, no markdown: {"more": "3-4 vivid accurate sentences"}. ' +
          "Go one level deeper on the page — new detail, mechanism, or story. Do not repeat anything already said.",
        `Page: "${title}".\nAlready said: ${[blurb, ...more].join(" ")}\nTell me more.`
      );
      if (j.more) patchPage(idx, title, (p) => ({ more: [...(p.more || []), j.more] }));
    } catch (e) {
      /* leave page as-is; button simply stops loading */
    } finally {
      setMoreLoading(false);
    }
  }

  async function askFollowUp() {
    const q = followQ.trim();
    if (!q || !current || qaLoading) return;
    const idx = trail.length - 1;
    const { title, blurb, more = [] } = current;
    setFollowQ("");
    setQaLoading(true);
    try {
      const j = await callClaude(
        PERSONA +
          ' Respond with ONLY JSON, no markdown: {"answer": "2-4 clear accurate sentences"}. ' +
          "Answer the user's follow-up question in the context of the page.",
        `Page: "${title}".\nPage says: ${[blurb, ...more].join(" ")}\nFollow-up question: ${q}`
      );
      if (j.answer) patchPage(idx, title, (p) => ({ qa: [...(p.qa || []), { q, a: j.answer }] }));
    } catch (e) {
      patchPage(idx, title, (p) => ({
        qa: [...(p.qa || []), { q, a: "That one didn't come through — try asking again." }],
      }));
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
    setRecap("loading");
    setView("recap");
    try {
      const j = await callClaude(
        PERSONA +
          ' Respond with ONLY JSON, no markdown: {"synthesis": "3 warm sentences naming the thread that ' +
          'quietly connects this walk — a real intellectual connection, not flattery", ' +
          '"thread": "one open question worth carrying into tomorrow, under 15 words"}',
        `The user wandered through, in order: ${path.join(" > ")}.\nClose the wander.`
      );
      setRecap({ path, synthesis: j.synthesis || "", thread: j.thread || "" });
    } catch (e) {
      setRecap("error");
    }
  }

  function keepWandering() {
    setRecap(null);
    setView(trail.length ? "page" : "home");
  }

  function startFresh() {
    reqId.current++;
    visitedRef.current = [];
    setRecap(null);
    setTrail([]);
    setError(null);
    clearPageExtras();
    setView("home");
    shuffleDoors(); // fresh hand of doors for the new wander
  }

  function toggleSave() {
    if (!current) return;
    setSaved((s) =>
      s.find((p) => p.title === current.title)
        ? s.filter((p) => p.title !== current.title)
        : [{ ...current }, ...s]
    );
  }

  function submitAsk() {
    const q = ask.trim();
    if (!q) return;
    setAsk("");
    openPage(q, "topic");
  }

  const isSaved = current && saved.some((p) => p.title === current.title);

  return (
    <div className="curio-root" ref={scrollRef} style={{ overflowY: "auto", height: "100%" }}>
      <style>{STYLE}</style>
      <div className="wrap">
        {/* header */}
        <div className="top">
          <div className="brandrow">
            <div className="brand" onClick={() => goToCrumb(-1)} role="button" tabIndex={0}
              onKeyDown={(e) => e.key === "Enter" && goToCrumb(-1)}>
              <span className="mark" />
              <h1>Curio</h1>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="saved-btn" onClick={() => setView("map")}>
                Trail{visitedRef.current.length ? <> · <b>{visitedRef.current.length}</b></> : ""}
              </button>
              <button className="saved-btn" onClick={() => setView("saved")}>
                Saved{saved.length ? <> · <b>{saved.length}</b></> : ""}
              </button>
            </div>
          </div>

          {view === "page" && (
            <div className="trail">
              <button className="crumb" onClick={() => goToCrumb(-1)}>Home</button>
              {trail.map((p, i) => (
                <React.Fragment key={i}>
                  <span className="sep">›</span>
                  <button className={"crumb" + (i === trail.length - 1 ? " here" : "")}
                    onClick={() => goToCrumb(i)}>{p.title}</button>
                </React.Fragment>
              ))}
            </div>
          )}
        </div>

        {/* HOME */}
        {view === "home" && (
          <div className="home">
            <div className="ey">Today's doors</div>
            <h2>Follow a thread of <i>curiosity</i>.</h2>
            <p className="lede">Tap a door to begin. Each page hands you a few new ones — deeper, adjacent, or delightfully sideways. You pick the direction.</p>
            <div className="doors-row">
              <div className="doors-label" style={{ margin: 0 }}>Pick a starting point</div>
              <button className="shuffle" onClick={shuffleDoors} title="Show me different doors">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M16 3h5v5" /><path d="M4 20 21 3" />
                  <path d="M21 16v5h-5" /><path d="m15 15 6 6" /><path d="M4 4l5 5" />
                </svg>
                Shuffle
              </button>
            </div>
            <div className="doors" key={seeds.map((s) => s.label).join("|")}>
              {seeds.map((s, i) => (
                <button key={s.label} className={"door " + s.type} onClick={() => openPage(s.label, s.type, true)}>
                  <span className="kind">{KIND_WORD[s.type] || "Path"}</span>
                  <span className="lbl">{s.label}</span>
                </button>
              ))}
            </div>
            <button className="door wild" style={{ marginTop: 10 }}
              onClick={() => openPage(null, "topic", true, true)}>
              <span className="kind">Wildcard</span>
              <span className="lbl">✦ Surprise me — somewhere I haven't been</span>
            </button>
            <div className="ask" style={{ marginTop: 22 }}>
              <input value={ask} onChange={(e) => setAsk(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submitAsk()}
                placeholder="…or start somewhere of your own" />
              <button onClick={submitAsk} disabled={!ask.trim()}>Explore</button>
            </div>
            <div className="foot">Follow your curiosity — one door at a time</div>
          </div>
        )}

        {/* PAGE */}
        {view === "page" && (
          <div className="page">
            {loading ? (
              <div className="loading"><span className="dots"><i /><i /><i /></span> Opening the door…</div>
            ) : error ? (
              <div className="errline">
                That door didn't open.
                <button onClick={() => openPage(error.label, error.type, error.resetTo, error.surprise)}>Try again</button>
              </div>
            ) : current ? (
              <>
                <h2>{current.title}</h2>
                <p className="blurb">{current.blurb}</p>
                {(current.more || []).map((m, i) => (
                  <p className="blurb deeper" key={i}>{m}</p>
                ))}
                <div className="save-row">
                  <button className={"save" + (isSaved ? " on" : "")} onClick={toggleSave}>
                    <svg viewBox="0 0 24 24" fill={isSaved ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2">
                      <path d="M6 3h12a1 1 0 0 1 1 1v16l-7-4-7 4V4a1 1 0 0 1 1-1z" />
                    </svg>
                    {isSaved ? "Saved" : "Save this page"}
                  </button>
                  <button className="save" onClick={tellMore} disabled={moreLoading}>
                    {moreLoading ? "Going deeper…" : "Tell me more"}
                  </button>
                </div>

                {((current.qa || []).length > 0 || qaLoading) && (
                  <div className="qa-list">
                    {(current.qa || []).map((x, i) => (
                      <div className="qa" key={i}>
                        <p className="q">{x.q}</p>
                        <p className="a">{x.a}</p>
                      </div>
                    ))}
                    {qaLoading && (
                      <div className="loading" style={{ padding: "10px 2px" }}>
                        <span className="dots"><i /><i /><i /></span> Thinking it over…
                      </div>
                    )}
                  </div>
                )}
                <div className="ask" style={{ marginBottom: 28 }}>
                  <input value={followQ} onChange={(e) => setFollowQ(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && askFollowUp()}
                    placeholder="Ask a follow-up about this…" />
                  <button onClick={askFollowUp} disabled={!followQ.trim() || qaLoading}>Ask</button>
                </div>

                <div className="next-label">Where to next?</div>
                <div className="doors">
                  {current.buttons.map((b, i) => (
                    <button key={i} className={"door " + b.type} onClick={() => openPage(b.label, b.type)}>
                      <span className="kind">{KIND_WORD[b.type] || "Path"}</span>
                      <span className="lbl">{b.label}</span>
                    </button>
                  ))}
                </div>
                <div className="ask">
                  <input value={ask} onChange={(e) => setAsk(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && submitAsk()}
                    placeholder="…or steer it yourself" />
                  <button onClick={submitAsk} disabled={!ask.trim()}>Go</button>
                </div>
                {visitedRef.current.length >= 3 ? (
                  <div className="close-row">
                    <button className="close-wander" onClick={closeWander}>✦ Close the wander</button>
                    <div className="foot" style={{ marginTop: 10 }}>Generated live by Claude</div>
                  </div>
                ) : (
                  <div className="foot">Generated live by Claude</div>
                )}
              </>
            ) : null}
          </div>
        )}

        {/* SAVED */}
        {view === "saved" && (
          <div className="saved-view">
            <h2>Saved pages</h2>
            <p className="sub">The stops worth keeping. Tap one to wander again from there.</p>
            {saved.length === 0 ? (
              <p className="empty">Nothing saved yet. When a page catches you, hit <b>Save this page</b> and it'll wait for you here.</p>
            ) : (
              saved.map((p, i) => (
                <button key={i} className="saved-item" onClick={() => openSaved(p)}>
                  <p className="t">{p.title}</p>
                  <p className="b">{p.blurb}</p>
                </button>
              ))
            )}
          </div>
        )}
        {/* MAP — where you've been */}
        {view === "map" && (
          <div className="map-view">
            <h2>Where you've been</h2>
            <p className="sub">Every branch of this wander — your map, not an algorithm's. Tap any stop to pick up from there.</p>
            {visitedRef.current.length === 0 ? (
              <p className="empty">No territory explored yet. Open a door and the map draws itself.</p>
            ) : (
              <div className="tree">
                {(function renderTree(parentId) {
                  const kids = visitedRef.current.filter((n) => (n.parentId ?? null) === parentId);
                  if (!kids.length) return null;
                  return kids.map((n) => (
                    <div className="tbranch" key={n.nodeId}>
                      <button
                        className={"tnode" + (current && current.nodeId === n.nodeId ? " here" : "")}
                        onClick={() => jumpToNode(n)}>
                        <span className={"tdot " + (n.kind || "topic")} />
                        <span className="tlbl">{n.title}</span>
                      </button>
                      {renderTree(n.nodeId)}
                    </div>
                  ));
                })(null)}
              </div>
            )}
            {visitedRef.current.length >= 3 && (
              <button className="save" style={{ marginTop: 22 }} onClick={closeWander}>✦ Close the wander</button>
            )}
          </div>
        )}
        {/* RECAP — the wander, closed */}
        {view === "recap" && (
          <div className="recap">
            <div className="ey">The wander, closed</div>
            {recap === "loading" ? (
              <div className="loading"><span className="dots"><i /><i /><i /></span> Reading back over your path…</div>
            ) : recap === "error" ? (
              <div className="errline">
                Couldn't close the book.
                <button onClick={closeWander}>Try again</button>
                <button onClick={keepWandering} style={{ marginLeft: 6 }}>Keep wandering</button>
              </div>
            ) : recap ? (
              <>
                <div className="recap-path">
                  {recap.path.map((t, i) => (
                    <React.Fragment key={i}>
                      {i > 0 && <span className="sep"> › </span>}
                      <span>{t}</span>
                    </React.Fragment>
                  ))}
                </div>
                <p className="recap-synth">{recap.synthesis}</p>
                {recap.thread && (
                  <div className="recap-thread">
                    <span className="tlabel">A thread to carry</span>
                    <button className="thread-q" onClick={() => { setRecap(null); openPage(recap.thread, "question", true); }}>
                      {recap.thread}
                    </button>
                  </div>
                )}
                <div className="recap-actions">
                  <button className="save" onClick={keepWandering}>Keep wandering</button>
                  <button className="save" onClick={startFresh}>Start fresh</button>
                </div>
              </>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}
