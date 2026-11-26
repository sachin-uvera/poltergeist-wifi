// Hosted replay demo: stands in for the hub.
//
// The real page talks to a Python hub over a WebSocket and a few /api/ calls. On a static
// host there is no hub, so this file plays the pre-computed JSON from data/ back into the
// same page by feeding it the same messages the hub would send. The page code is unchanged.
//
// Only motion scores, states, ghost positions and event text are in those files.
//
// URL options:  ?rec=walk  start with another recording     ?speed=8  play faster
(function () {
  "use strict";
  const params = new URLSearchParams(location.search);
  const speed = Math.max(0.25, Math.min(60, parseFloat(params.get("speed")) || 1));
  const ALARM = new Set(["possible_fall", "fall", "inactive_too_long"]);

  let handle = null;          // the page's message handler
  let manifest = [];          // [{label, title, filename, file, duration_s}]
  let timer = null;
  let run = 0;                // bumped on every start/stop so a slow fetch cannot start a stale run
  let current = null;         // manifest entry on screen
  let lastState = "empty";

  const hhmm = () => new Date().toTimeString().slice(0, 5);
  const ok = (body) => Promise.resolve({ ok: true, json: () => Promise.resolve(body || {}) });
  const fail = (error, status) => Promise.resolve({ ok: false, status: status || 409, json: () => Promise.resolve({ error }) });

  function find(name) {
    return manifest.find(m => m.label === name || m.filename === name || m.file === name);
  }

  function stop() {
    run++;
    if (timer) { clearInterval(timer); timer = null; }
  }

  function send(msg) { if (handle) handle(msg); }

  async function start(name) {
    const entry = find(name);
    if (!entry) return fail("recording not found: " + name, 404);
    stop();
    const myRun = run;
    let doc;
    try {
      const r = await fetch("data/" + entry.file, { cache: "no-cache" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      doc = await r.json();
    } catch (e) {
      return fail("could not load the recording (" + e.message + ")", 502);
    }
    if (myRun !== run) return ok({});       // another start/stop happened while loading

    current = entry;
    lastState = "empty";
    // Reset the screen like the hub does at the start of a replay. No "recordings" key,
    // so the dropdown keeps the visitor's choice.
    send({ type: "init", mode: "replay", recording: entry.filename, events: [], scores: {},
           active_links: [], ghosts: [], room_state: "empty", calibrating: false });

    // Skip the empty-room lead-in: start 4 s before the first event (a visitor should not
    // wait half a minute for something to happen). Recordings with no events play in full.
    const skip = doc.events.length ? Math.max(0, doc.events[0].t - 4) : 0;
    const t0 = performance.now();
    let ti = 0, ei = 0;
    while (ti < doc.ticks.length && doc.ticks[ti].t < skip) ti++;
    timer = setInterval(() => {
      const now = (performance.now() - t0) / 1000 * speed + skip;
      while (ti < doc.ticks.length && doc.ticks[ti].t <= now) {
        const tk = doc.ticks[ti++];
        // an event is sent just before the tick that follows it, as the hub does
        while (ei < doc.events.length && doc.events[ei].t <= tk.t) {
          const ev = doc.events[ei++];
          lastState = ev.state;
          send({ type: "event", room_state: ev.state,
                 event: { icon: ev.icon, kind: ev.kind, note: ev.note, ts: hhmm(),
                          text: ev.text + ", " + hhmm() } });
        }
        lastState = tk.state;
        send({ type: "tick", scores: tk.scores, active_links: tk.active,
               room_state: tk.state, ghosts: tk.ghosts });
      }
      if (ti >= doc.ticks.length) {
        clearInterval(timer); timer = null;
        send({ type: "mode", mode: "idle", recording: entry.filename });
      }
    }, 100);
    return ok({ started: entry.filename });
  }

  // The page's calls to the hub, answered here.
  function post(url, body) {
    if (url === "/api/replay") return start((body && body.recording) || "");
    if (url === "/api/acknowledge") {
      if (!ALARM.has(lastState)) return fail("nothing to acknowledge");
      stop();
      lastState = "empty";
      send({ type: "event", room_state: "empty",
             event: { icon: "\u2705", kind: "reset", note: "acknowledged", ts: hhmm(),
                      text: "\u2705 Alert acknowledged, " + hhmm() } });
      send({ type: "tick", scores: {}, active_links: [], room_state: "empty", ghosts: [] });
      send({ type: "mode", mode: "idle", recording: current ? current.filename : "" });
      return ok({ acknowledged: true });
    }
    if (url === "/api/stop") { stop(); send({ type: "mode", mode: "idle", recording: current ? current.filename : "" }); return ok({}); }
    return fail("Not available in the hosted demo (it replays recordings only)");
  }

  async function loadManifest() {
    const r = await fetch("data/index.json", { cache: "no-cache" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    manifest = await r.json();
    return manifest;
  }

  document.documentElement.classList.add("demo");

  window.GG_DEMO = {
    post,
    recordings: () => loadManifest().then(list => list.map(m => ({ label: m.label, filename: m.filename, title: m.title }))),
    // Called by the page once its message handler exists.
    attach(fn) {
      handle = fn;
      loadManifest().then(list => {
        send({ type: "init", mode: "idle", recording: "", events: [], scores: {}, active_links: [],
               ghosts: [], room_state: "empty", calibrating: false,
               recordings: list.map(m => ({ label: m.label, filename: m.filename, title: m.title })) });
        const first = params.get("rec") || (find("fall") ? "fall" : (list[0] && list[0].label));
        if (first && params.get("rec") !== "none") {
          const sel = document.getElementById("rec-select");
          if (sel) sel.value = (find(first) || {}).label || sel.value;
          start(first);
        }
      }).catch(e => {
        const list = document.getElementById("event-list");
        if (list) list.textContent = "Could not load the demo data (" + e.message + ").";
      });
    },
  };
})();
