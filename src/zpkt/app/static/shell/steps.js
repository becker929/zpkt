// Steps: the step sequencer on the Song tab. Served at /app/shell/steps.js; the styles are steps.css. A classic
// script, loaded after the app's own: it uses window.zpkt (the app's state, its command() and its Song) and gives
// window.zpktSteps back. The page makes no sound: a tap writes a note into Live's Arrangement clip, and Live plays.
//
// A pattern is 1, 2 or 4 bars of one MIDI track from a bar of the song. The screen shows one bar of it at a time:
// an overview with a row for each sound, and the chosen sound's 16 steps as two rows of 8 pads, the MiniLab's pad
// banks A (steps 1 to 8) and B (steps 9 to 16).
//
//   open(track)   show Steps for a MIDI track of the Song (by its name)
//   close()       back to the lanes
//   render()      draw what is open again (the app's renderSong calls it while Steps or the kit picker shows)
//   click(button) a press on one of this file's keys (the app's one click listener hands it over)
//   songKeys(t)   the keys a chosen MIDI lane gets in the Song's strip; newKey(view): the key that makes a drum track
//   painting(name), lane(t, bars), songSel(t)   Paint: the chosen lane as cells of the pattern's length, and its strip
//   message(m)    the app's {"t": "steps"} message: the focus, and a pattern changed by another hand
//   live()        Live's playhead or loop moved: the step under the playhead is outlined, the loop key follows
//
// Paint is on the Song's own lanes: the chosen MIDI lane grows and shows one cell per pattern length across the
// song. Lime: that bar holds the pattern in hand (the clip's notes hash the same). Grey: another clip of that
// length. Hatched: clips are in the way. A tap or a drag across cells paints them (one steps.paint a gesture); with
// Erase lit it erases.
//
// The focus: while Steps shows, the app is told what is in hand (steps.focus: the pattern, the sound, the values a
// new step gets, the sound's steps), and told nothing is when it closes. The MiniLab's pads are mapped to that.
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const app = () => window.zpkt;
  const PER = 16;  // the steps of a bar
  const ROW_MIN = 24;  // px: the least height of an overview row; fewer rows show when they do not fit
  const ST = {open: false, pick: null, track: "", bar: 1, bars: 1, view: 0, pitch: null, data: null, at: 0, per: 8,
              seq: 0, loading: false, velocity: 100, length: 1, swing: 0,
              focus: null, ph: -1, looping: false, loopWas: null, told: Promise.resolve(), painting: false, erase: false,
              last: null, clearAt: 0};
  const SRC = "page-" + Math.random().toString(36).slice(2, 8);  // this page's word on its own commands
  const icon = (n, size = 18) => `<svg width="${size}" height="${size}" aria-hidden="true"><use href="#i-${n}"/></svg>`;
  const esc = (t) => app().esc(t);
  const trackOf = (name) => { const v = app().S.song.view; return (v && v.tracks.find((t) => t.name === name)) || null; };
  const rows = () => (ST.data ? ST.data.pattern.rows : []);
  const rowOf = (pitch) => rows().find((r) => r.pitch === pitch) || null;
  const blocked = () => !!(ST.data && ST.data.blocked && ST.data.blocked.length);
  const spanKey = () => `${ST.track}/${ST.bar}/${ST.bars}`;
  const clamp = (n) => Math.max(0, Math.min(1, n));
  // The three knobs, as places 0 to 1. Velocity is 1 to 127. Length is a note's length in steps, on stops. Swing is
  // how late every second step is, up to three quarters of a step.
  const LENGTHS = [0.25, 0.5, 1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64];
  const lengths = () => LENGTHS.filter((v) => v <= ST.bars * PER);
  const LEN_TEXT = {0.25: "1/64", 0.5: "1/32", 1: "1/16", 2: "1/8", 3: "3/16", 4: "1/4", 6: "3/8", 8: "1/2", 12: "3/4", 16: "1 bar", 24: "1.5 bars", 32: "2 bars", 48: "3 bars", 64: "4 bars"};
  const nearest = (list, v) => list.reduce((best, x, i) => (Math.abs(x - v) < Math.abs(list[best] - v) ? i : best), 0);
  const KNOBS = {
    velocity: {label: "Velocity", n: () => (ST.velocity - 1) / 126, text: () => String(ST.velocity), to: (n) => 1 + Math.round(clamp(n) * 126), stops: () => 0, step: 1 / 126},
    length: {label: "Length", n: () => nearest(lengths(), ST.length) / Math.max(1, lengths().length - 1), text: () => LEN_TEXT[lengths()[nearest(lengths(), ST.length)]],
             to: (n) => lengths()[Math.round(clamp(n) * (lengths().length - 1))], stops: () => lengths().length, step: 0},
    swing: {label: "Swing", n: () => ST.swing / 0.75, text: () => `${Math.round(ST.swing * 100)}%`, to: (n) => Math.round(clamp(n) * 75) / 100, stops: () => 0, step: 1 / 75},
  };
  const perBar = () => (ST.data && ST.data.beats_per_bar) || app().songOf().beats_per_bar || 4;
  // Is Live looping exactly the pattern in hand?
  function looped() {
    const st = app().S.state, sp = st && st.loop_span, per = perBar();
    return !!(st && st.loop && st.loop !== "off" && sp && Math.abs(sp[0] - (ST.bar - 1) * per) < 1e-6 && Math.abs(sp[1] - ST.bars * per) < 1e-6);
  }
  const shown = () => ST.open || !!ST.pick;

  // ---- the Song's own keys ------------------------------------------------------------------------------------------
  function songKeys(t) {
    return t && t.midi ? `<button class="key sm" type="button" data-st="open" aria-label="Steps: ${esc(t.name)}">${icon("steps")}Steps</button>`
      + `<button class="key sm" type="button" data-st="paint" aria-pressed="false" aria-label="Paint: ${esc(t.name)}">${icon("paint")}Paint</button>` : "";
  }

  // ---- Paint, on the Song's lanes ---------------------------------------------------------------------------------
  // Is the lane called `name` the one being painted? Choosing another lane, or none, ends painting.
  function painting(name) {
    if (ST.painting && (ST.open || app().S.song.sel !== ST.track)) ST.painting = false;
    return ST.painting && ST.track === name;
  }
  // The chosen lane's inside while it is painted: one cell per pattern length, from the pattern's own bar outward.
  function lane(t, total) {
    if (!painting(t.name)) return null;
    const n = ST.bars, off = (ST.bar - 1) % n, count = Math.max(0, Math.floor((total - off) / n)), per = perBar(), d = ST.data;
    const have = new Map(((d && d.painted) || []).map((c) => [c.bar, c.hash])), mine = d && d.clip ? d.hash : null;
    let cells = "";
    for (let k = 0; k < count; k++) {
      const bar = off + 1 + k * n, from = (bar - 1) * per, to = from + n * per, hash = have.get(bar);
      const exact = (r) => Math.abs(r.start - from) < 1e-6 && Math.abs(r.end - to) < 1e-6;
      const kind = hash !== undefined ? (hash === mine ? "p" : "o") : t.regions.some((r) => r.start < to - 1e-6 && r.end > from + 1e-6 && !exact(r)) ? "x" : "";
      cells += `<i class="st-cell ${kind} ${bar === ST.bar ? "src" : ""} ${stroke && stroke.picked.has(bar) ? "pend" : ""}" data-bar="${bar}" style="left:${((bar - 1) / total * 100).toFixed(3)}%;width:calc(${(n / total * 100).toFixed(3)}% - 1px)"></i>`;
    }
    return `<div class="st-cells ${ST.erase ? "erasing" : ""}" data-total="${total}" role="group" aria-label="Paint ${esc(t.name)}">${cells}</div>`;
  }
  // The strip under the lanes while painting: the pattern small, the track, Steps, Erase, Paint (lit).
  function songSel(t) {
    if (!painting(t.name)) return null;
    const shown = rows().filter((r) => r.steps.some(Boolean)).slice(0, 8), list = shown.length ? shown : rows().slice(0, 4);
    const thumb = list.map((r) => r.steps.slice(0, PER).map((v) => `<i class="${v ? "on" : ""}"></i>`).join("")).join("");
    return `<span class="st-thumb" id="st-thumb" role="img" aria-label="The pattern at bar ${ST.bar}">${thumb}</span><span class="sn">${t.color ? `<i class="cd" style="background:${esc(t.color)}"></i>` : ""}<b>${esc(t.name)}</b></span>`
      + `<button class="key sm" type="button" data-st="steps" aria-label="Steps: ${esc(t.name)}">${icon("steps")}Steps</button>`
      + `<button class="key sm ${ST.erase ? "on" : ""}" type="button" data-st="erase" aria-pressed="${ST.erase}" aria-label="Erase">${icon("erase")}Erase</button>`
      + `<button class="key sm on" type="button" data-st="paint" aria-pressed="true" aria-label="Paint">${icon("paint")}Paint</button>`;
  }
  // Paint for a track: with the pattern Steps had in hand on it, else the one at the loop's first bar or the playhead.
  function paintOn(name) {
    if (!trackOf(name)) return;
    const keep = ST.track === name && ST.data;
    if (ST.open) leaveSteps();
    if (!keep) Object.assign(ST, {track: name, bar: startBar(), bars: 1, view: 0, pitch: null, data: null, at: 0});
    Object.assign(ST, {open: false, pick: null, painting: true, erase: false});
    app().S.song.sel = name;
    app().renderSong();
    load(true);  // the pattern's clip and hash as Live has them now, and which bars hold it
  }
  function paintOff() { ST.painting = false; ST.erase = false; app().renderSong(); }
  // A gesture on the cells: a tap is one cell, a drag every cell it crosses. One command when the hand lifts. The
  // gesture keeps bars, not elements: the lane may be drawn again under the hand (Live says a clip changed).
  let stroke = null;
  const cellsBox = () => $("#lanes .lane.paint .st-cells");
  function cellIndex(x) {
    const box = cellsBox();
    if (!box) return -1;
    const rect = box.getBoundingClientRect(), total = +box.dataset.total, n = ST.bars, off = (ST.bar - 1) % n;
    const bar = Math.floor((x - rect.left) / rect.width * total);
    return Math.max(0, Math.min(box.children.length - 1, Math.floor((bar - off) / n)));
  }
  function strokeTo(index) {
    const box = cellsBox();
    if (!box || index < 0) return;
    const lo = Math.min(stroke.last, index), hi = Math.max(stroke.last, index);
    for (let i = lo; i <= hi && stroke.picked.size < 64; i++) {
      const bar = +box.children[i].dataset.bar;
      stroke.picked.add(bar); box.children[i].classList.add("pend");
    }
    stroke.last = index;
  }
  document.addEventListener("pointerdown", (e) => {
    const cell = e.target.closest && e.target.closest(".st-cell");
    if (!cell || !ST.painting || e.button > 0) return;
    stroke = {erase: ST.erase, picked: new Set(), last: cellIndex(e.clientX)};
    strokeTo(stroke.last);
    e.preventDefault();
  });
  document.addEventListener("pointermove", (e) => { if (stroke) strokeTo(cellIndex(e.clientX)); });
  document.addEventListener("pointercancel", () => { if (stroke) { stroke = null; app().renderSong(); } });
  document.addEventListener("pointerup", async () => {
    const st = stroke, box = cellsBox();
    stroke = null;
    if (!st) return;
    const bars = [...st.picked].sort((a, b) => a - b).filter((b) => st.erase || b !== ST.bar);
    if (!bars.length || !box || !ST.painting) return app().renderSong();
    const common = {track: ST.track, total_bars: +box.dataset.total, src: SRC};
    const r = await (st.erase ? app().command("steps.erase", {...common, bars, length: ST.bars}) : app().command("steps.paint", {...common, from_bar: ST.bar, bars: ST.bars, to: bars}));
    if (r.ok && ST.data) ST.data.painted = r.body.clips;
    if (r.ok && st.erase && bars.includes(ST.bar)) return load(true);  // the pattern's own clip went: read it again
    app().renderSong();
  });
  // With no MIDI track in the set there is nothing to put a pattern on: one key makes a drum track.
  function newKey(view) {
    return view && !view.tracks.some((t) => t.midi) ? `<button class="key sm" type="button" data-st="pick" aria-label="New drum track">${icon("plus")}${icon("steps")}Drum track</button>` : "";
  }

  // ---- the kit picker -----------------------------------------------------------------------------------------------
  async function pick() {
    ST.pick = {kits: null, at: 0, per: 8, busy: null};
    render();
    const r = await app().slowly(() => app().command("steps.kits"));
    if (!ST.pick) return;
    ST.pick.kits = r.ok ? r.body.kits : [];
    render();
  }
  function drawPicker() {
    const p = ST.pick, kits = p.kits || [];
    const list = p.kits === null ? "" : !kits.length ? '<div class="tag" id="st-nokits">No kits in Live’s browser</div>'
      : `<div class="st-kits" id="st-kits" role="group" aria-label="Drum kits">${kits.map((k, i) => `<button class="key sm ${p.busy === k ? "is-waiting" : ""}" type="button" data-st="kit" data-kit="${esc(k)}" data-i="${i}" ${p.busy ? "disabled" : ""}><span>${esc(k)}</span></button>`).join("")}</div>`;
    setSong(`<div id="stpick"><div class="st-bar"><span class="sn">${icon("steps")}<b>Drum kit</b></span><button class="key sm" type="button" data-st="unpick" aria-label="Close">${icon("x")}</button></div>${list}${pager("st-kpgs", "kitstep", "Kits")}</div>`);
    fitPicker();
  }
  const pager = (id, step, what) => `<div class="pgs" id="${id}" role="group" aria-label="More ${what.toLowerCase()}" hidden><button class="key sm" type="button" data-st="${step}" data-by="-1" aria-label="${what} before"><svg class="back" width="18" height="18"><use href="#i-more"/></svg></button><span class="pgn"></span><button class="key sm" type="button" data-st="${step}" data-by="1" aria-label="${what} after">${icon("more")}</button></div>`;
  function setPager(bar, at, per, total) {
    const parts = Math.max(1, Math.ceil(total / per));
    bar.hidden = parts < 2;
    bar.querySelector(".pgn").textContent = `${at * per + 1}–${Math.min(total, at * per + per)} / ${total}`;
    bar.querySelector('[data-by="-1"]').disabled = at === 0;
    bar.querySelector('[data-by="1"]').disabled = at >= parts - 1;
  }
  // The kits that fit the height, in as many columns as the width holds; the rest are a page away.
  function fitPicker() {
    const box = $("#st-kits"), bar = $("#st-kpgs"), p = ST.pick;
    if (!box || !bar || !p) return;
    const keys = [...box.children], cols = Math.max(1, Math.min(4, Math.floor(box.clientWidth / 170)));
    box.style.setProperty("--cols", cols);
    const fit = (h) => Math.max(1, Math.floor((h + 6) / 50)) * cols;
    bar.hidden = true;
    let per = fit(box.clientHeight);
    if (keys.length > per) { bar.hidden = false; per = fit(box.clientHeight); }
    p.per = per; p.at = Math.max(0, Math.min(Math.ceil(keys.length / per) - 1, p.at));
    keys.forEach((k, i) => { k.hidden = Math.floor(i / per) !== p.at; });
    setPager(bar, p.at, per, keys.length);
  }
  // The new track's name: "Drums", or "Drums 2", "Drums 3" where the set has one.
  function freeName() {
    const v = app().S.song.view, have = new Set(v ? v.tracks.map((t) => t.name) : []);
    for (let n = 1; ; n++) { const name = n === 1 ? "Drums" : `Drums ${n}`; if (!have.has(name)) return name; }
  }
  async function makeTrack(kit) {
    const p = ST.pick;
    if (!p || p.busy) return;
    p.busy = kit; render();
    const name = freeName(), r = await app().slowly(() => app().command("steps.new_track", {name, kit}));
    if (ST.pick !== p) return;
    if (!r.ok) { p.busy = null; return render(); }
    ST.pick = null;
    app().S.song.sel = r.body.track;
    await app().readSong();
    open(r.body.track);
  }

  // ---- Steps ----------------------------------------------------------------------------------------------------------
  // The bar Steps opens on: the loop's first bar when a loop is on, else the bar under the playhead.
  function startBar() {
    const z = app(), lb = z.loopBars(), st = z.S.state, per = z.songOf().beats_per_bar || 4;
    return lb ? lb[0] : Math.max(1, Math.floor(((st && st.pos) || 0) / per) + 1);
  }
  // `keep`: with the pattern already in hand on this track (coming from Paint), not the bar under the playhead.
  function open(name, keep) {
    if (!trackOf(name)) return;
    if (!(keep && ST.track === name && ST.data)) Object.assign(ST, {track: name, bar: startBar(), bars: 1, view: 0, pitch: null, data: null, at: 0});
    Object.assign(ST, {open: true, pick: null, painting: false, erase: false, looping: false, loopWas: null});
    render();
    load(!!ST.data);
  }
  // Steps is left (closed, or for Paint): the app is told nothing is in hand, and the loop goes back to what it was.
  function leaveSteps() {
    ST.open = false; ST.seq++;
    tell(null);
    if (ST.loopWas) app().command("steps.loop", {was: ST.loopWas}, undefined, true);
    ST.loopWas = null; ST.looping = false;
  }
  function close() {
    leaveSteps();
    ST.pick = null;
    app().renderSong();
  }
  // Tell the app what is in hand (or, with null, that nothing is), one message after the other.
  function tell(what) {
    const row = rowOf(ST.pitch);
    const args = what === null ? {} : row && ST.data ? {track: ST.track, bar: ST.bar, bars: ST.bars, steps_per_bar: PER, view: ST.view, pitch: row.pitch, name: row.name,
      velocity: ST.velocity, length: ST.length, swing: ST.swing, steps: row.steps.slice(), blocked: blocked()} : null;
    if (!args) return;
    ST.told = ST.told.then(() => app().command("steps.focus", {...args, src: SRC}, undefined, true)).catch(() => {});
  }
  // Read the pattern at the bar in hand. A reply to a question that is no longer the newest is dropped. `quiet`:
  // another hand changed it, and the pads stay in use while it is read again.
  async function load(quiet) {
    const mine = ++ST.seq, z = app(), v = z.S.song.view;
    if (!quiet) { ST.loading = true; sync(); }
    // no word of swing: the app keeps the swing each pattern was written with, and answers with it
    const r = await z.command("steps.read", {track: ST.track, bar: ST.bar, bars: ST.bars, total_bars: Math.max(1, (v && v.bars) || 0, z.songOf().bars || 0)});
    if (mine !== ST.seq || !(ST.open || ST.painting)) return;
    ST.loading = false;
    ST.data = r.ok ? r.body : null;
    if (ST.data) ST.swing = ST.data.pattern.swing || 0;  // the swing the pattern was written with
    if (!rowOf(ST.pitch)) ST.pitch = rows().length ? rows()[0].pitch : null;
    ST.view = Math.min(ST.view, ST.bars - 1);
    if (!ST.open) return app().renderSong();  // Paint: the lane's cells and the strip
    render();
    tell();
  }
  function setSong(html) {
    const box = $("#song");
    if (box.__st === html && box.firstElementChild && /^st/.test(box.firstElementChild.id)) return;
    box.innerHTML = html; box.__st = html;
  }
  // The frame: what does not change with a tap. sync() then lights the cells and the pads in place, so a pad is the
  // same element from one tap to the next.
  function draw() {
    const t = trackOf(ST.track);
    if (!t) return close();  // the track is gone from the set
    const cells = Array.from({length: PER}, (_, k) => `<i class="c ${k % 4 === 0 ? "b" : ""}"></i>`).join("");
    const ov = rows().map((r) => `<button class="st-row" type="button" data-st="sound" data-pitch="${r.pitch}" aria-pressed="false" aria-label="${esc(r.name)}"><span class="n" title="${esc(r.name)}">${esc(r.name)}</span>${cells}</button>`).join("");
    const pads = (from) => `<div class="st-pads" role="group" aria-label="Steps ${from + 1} to ${from + 8}">${Array.from({length: 8}, (_, k) => `<button class="st-pad ${(from + k) % 4 === 0 ? "beat" : ""}" type="button" data-st="pad" data-k="${from + k}" aria-pressed="false" aria-label="Step ${from + k + 1}">${from + k + 1}</button>`).join("")}</div>`;
    const MC = window.zpktControls;
    MC.panel([]);  // the knob's gradients are in the document (the Desk draws them too)
    const knobs = Object.entries(KNOBS).map(([key, k], i) => MC.slot({slot: `k${i + 1}`, state: "live", key, label: k.label, shown: k.text(), n: k.n(), steps: k.stops()})).join("");
    const seg = (name, list, word) => `<div class="seg" id="st-${name}" role="group" aria-label="${word}">${list.map((v) => `<button class="key sm" type="button" data-st="${name}" data-v="${v}" aria-pressed="false" aria-label="${word}: ${name === "view" ? v + 1 : v}">${name === "view" ? v + 1 : v}</button>`).join("")}</div>`;
    setSong(`<div id="steps" data-track="${esc(ST.track)}" data-bars="${ST.bars}">
      <div class="st-bar"><span class="sn">${t.color ? `<i class="cd" style="background:${esc(t.color)}"></i>` : ""}<b>${esc(ST.track)}</b></span>
        ${seg("bars", [1, 2, 4], "Bars in the pattern")}
        <button class="key sm" type="button" data-st="loop" aria-pressed="false" aria-label="Loop this pattern">${icon("loop")}</button>
        <button class="key sm" type="button" data-st="close" aria-label="Close Steps">${icon("x")}</button></div>
      <div class="st-bar"><button class="key sm" type="button" data-st="bar" data-by="-1" aria-label="Pattern before"><svg class="back" width="18" height="18" aria-hidden="true"><use href="#i-more"/></svg></button>
        <span class="st-barn" id="st-barn" role="status"></span>
        <button class="key sm" type="button" data-st="bar" data-by="1" aria-label="Pattern after">${icon("more")}</button>
        <span class="sp"></span>${ST.bars > 1 ? seg("view", Array.from({length: ST.bars}, (_, k) => k), "Bar of the pattern") : ""}</div>
      <div class="st-ov" id="st-ov" role="group" aria-label="Sounds">${ov}</div>
      <div class="st-ml"><div class="st-head"><b id="st-name"></b>
          <button class="key sm" type="button" data-st="snd" data-by="-1" aria-label="Sound before"><svg class="up" width="18" height="18" aria-hidden="true"><use href="#i-more"/></svg></button>
          <button class="key sm" type="button" data-st="snd" data-by="1" aria-label="Sound after"><svg class="dn" width="18" height="18" aria-hidden="true"><use href="#i-more"/></svg></button><span class="sp"></span>
          <button class="key sm" type="button" data-st="clear" id="st-clear" aria-label="Clear this sound">${icon("clear")}<span>Clear</span></button>
          <button class="key sm" type="button" data-st="paint" aria-label="Paint this pattern">${icon("paint")}Paint</button></div>
        <div class="st-knobs" id="st-knobs" role="group" aria-label="The step in hand">${knobs}</div>
        <span class="tag">pads A</span>${pads(0)}<span class="tag">pads B</span>${pads(8)}</div></div>`);
    ST.ph = -1;
    fit(); sync(); live();
  }
  // As many sound rows as the height holds (8 at most): the part of the kit with the chosen sound in it. The keys
  // by the sound's name step to the sound before or after, so every sound is reached without a scroll.
  function fit() {
    const ov = $("#st-ov");
    if (!ov || $("#song").hidden) return;
    const all = [...ov.children];
    all.forEach((r) => { r.hidden = true; });  // measured empty: the rows give the box no height of their own
    const per = ST.per = Math.max(1, Math.min(8, Math.floor((ov.clientHeight + 2) / (ROW_MIN + 2))));
    const chosen = Math.max(0, all.findIndex((r) => +r.dataset.pitch === ST.pitch));
    ST.at = Math.floor(chosen / per);
    all.forEach((r, i) => { r.hidden = Math.floor(i / per) !== ST.at; });
  }
  function sync() {
    const box = $("#steps");
    if (!box) return;
    if (ST.loading) box.dataset.loading = "1"; else delete box.dataset.loading;
    const barn = $("#st-barn"), off = blocked(), from = ST.view * PER;
    barn.textContent = `Bar ${ST.bar + ST.view}`;
    if (off) { barn.dataset.blocked = "1"; barn.title = "Clips are in the way"; barn.setAttribute("aria-label", `Bar ${ST.bar + ST.view}: clips are in the way`); }
    else { delete barn.dataset.blocked; barn.removeAttribute("title"); barn.removeAttribute("aria-label"); }
    box.querySelector('[data-st="bar"][data-by="-1"]').disabled = ST.bar <= 1;
    const lk = box.querySelector('[data-st="loop"]'), on = looped();
    lk.classList.toggle("on", on); lk.setAttribute("aria-pressed", String(on));
    for (const key of box.querySelectorAll('[data-st="bars"], [data-st="view"]')) {
      const lit = +key.dataset.v === (key.dataset.st === "bars" ? ST.bars : ST.view);
      key.classList.toggle("on", lit); key.setAttribute("aria-pressed", String(lit));
    }
    syncKnobs(); syncClear();
    for (const el of box.querySelectorAll(".st-row")) {
      const row = rowOf(+el.dataset.pitch), sel = +el.dataset.pitch === ST.pitch;
      el.classList.toggle("sel", sel); el.setAttribute("aria-pressed", String(sel));
      el.querySelectorAll(".c").forEach((c, k) => c.classList.toggle("on", !!(row && row.steps[from + k])));
    }
    const mine = rowOf(ST.pitch), nth = rows().indexOf(mine);
    $("#st-name").textContent = mine ? mine.name : "";
    box.querySelector('[data-st="snd"][data-by="-1"]').disabled = nth <= 0;
    box.querySelector('[data-st="snd"][data-by="1"]').disabled = nth < 0 || nth >= rows().length - 1;
    for (const pad of box.querySelectorAll(".st-pad")) {
      const v = mine ? mine.steps[from + +pad.dataset.k] : 0;
      pad.classList.toggle("on", !!v); pad.classList.toggle("soft", v > 0 && v < 80);
      pad.classList.toggle("last", !!v && !!lastStep() && ST.last.step === from + +pad.dataset.k);
      pad.setAttribute("aria-pressed", String(!!v));
      pad.disabled = off || !mine || !ST.data;
    }
  }
  // The step touched last, while it is still on: the one the Velocity and Length knobs change.
  function lastStep() {
    const L = ST.last, row = L && L.at === spanKey() && L.pitch === ST.pitch ? rowOf(L.pitch) : null;
    return row && row.steps[L.step] ? L : null;
  }
  function syncKnobs() {
    for (const el of document.querySelectorAll("#st-knobs .mc")) {
      const k = KNOBS[el.dataset.key], n = clamp(k.n()), text = k.text(), v = el.querySelector(".v");
      if (Math.abs(+el.dataset.n - n) > 1e-9) window.zpktControls.set(el, n);
      if (v.textContent !== text) { v.textContent = text; el.querySelector(".w").setAttribute("aria-valuetext", text); }
    }
  }
  // Clear takes the chosen sound's row out; pressed again within three seconds, the whole pattern. The key says
  // which of the two the next press is.
  function syncClear() {
    const key = $("#st-clear"), armed = Date.now() - ST.clearAt < 3000;
    if (!key) return;
    key.classList.toggle("ask", armed);
    key.querySelector("span").textContent = armed ? "All" : "Clear";
    key.setAttribute("aria-label", armed ? "Clear the whole pattern" : "Clear this sound");
    key.disabled = blocked() || !ST.data;
  }
  // One command of a kind is in the air; the newest waits and older ones are dropped, so a turned knob never queues.
  const LINE = {};
  async function inLine(kind, work) {
    const q = LINE[kind] || (LINE[kind] = {busy: false, next: null});
    if (q.busy) { q.next = work; return; }
    q.busy = true;
    try { await work(); } finally {
      q.busy = false;
      if (q.next) { const next = q.next; q.next = null; inLine(kind, next); }
    }
  }
  // What Live has of the pattern, read again: a write of the whole pattern starts from Live's notes, not the page's.
  async function fresh() {
    const at = spanKey(), r = await app().command("steps.read", {track: ST.track, bar: ST.bar, bars: ST.bars}, undefined, true);
    return r.ok && at === spanKey() ? r.body : null;
  }
  // Write the whole pattern (swing, clear) and take Live's answer as the pattern on the page.
  async function put(pattern, more) {
    const at = spanKey(), r = await app().command("steps.write", {track: ST.track, bar: ST.bar, pattern, ...more, src: SRC});
    if (r.ok && at === spanKey() && ST.data) { Object.assign(ST.data, {pattern: r.body.pattern, clip: r.body.clip, hash: r.body.hash, off_grid: r.body.off_grid, blocked: r.body.blocked}); sync(); tell(); }
    return r;
  }
  const asWritten = (p, change) => ({bars: p.bars, steps_per_bar: PER, length: p.length, swing: p.swing || 0,
    rows: p.rows.map((r) => ({pitch: r.pitch, name: r.name, steps: r.steps.slice(), ...(r.lengths ? {lengths: r.lengths.slice()} : {})})), ...change});
  // A knob was turned to place n.
  function knobTo(what, n) {
    const k = KNOBS[what], value = k.to(n);
    if (value === ST[what]) return;
    ST[what] = value;
    syncKnobs();
    const L = lastStep();
    if (what === "swing") inLine("swing", async () => {
      const now = await fresh();
      if (!now || !now.clip || !now.pattern.rows.some((r) => r.steps.some(Boolean))) return;  // nothing to move yet: new steps get it
      await put(asWritten(now.pattern, {swing: ST.swing}));
    });
    else if (L) {
      if (what === "velocity") { rowOf(L.pitch).steps[L.step] = value; sync(); }
      inLine("set-" + what, () => app().command("steps.set", {track: ST.track, bar: ST.bar, bars: ST.bars, pitch: L.pitch, step: L.step, [what]: value, swing: ST.swing, src: SRC}));
    }
  }
  let turn = null;  // a hand on a knob: it moves from where it is, 200 px across its range; Shift is fine
  document.addEventListener("pointerdown", (e) => {
    const w = e.target.closest && e.target.closest("#st-knobs .mc .w"), el = w && w.closest(".mc");
    if (!el || e.button > 0) return;
    w.focus({preventScroll: true});
    turn = {what: el.dataset.key, y: e.clientY, at: +el.dataset.n || 0, finger: e.pointerType === "touch", moved: false};
    if (w.setPointerCapture) try { w.setPointerCapture(e.pointerId); } catch (err) { /* a pointer that is already gone */ }
    e.preventDefault();
  });
  document.addEventListener("pointermove", (e) => {
    if (!turn) return;
    const dy = turn.y - e.clientY;
    if (!turn.moved && turn.finger && Math.abs(dy) < 4) return;
    turn.moved = true;
    knobTo(turn.what, clamp(turn.at + dy / 200 * (e.shiftKey ? 0.2 : 1)));
  });
  const endTurn = () => { if (turn) { turn = null; tell(); } };
  document.addEventListener("pointerup", endTurn);
  document.addEventListener("pointercancel", endTurn);
  document.addEventListener("keydown", (e) => {
    const w = e.target.closest && e.target.closest("#st-knobs .mc .w"), el = w && w.closest(".mc");
    const dir = {ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1}[e.key];
    if (!el || !dir) return;
    e.preventDefault();
    const k = KNOBS[el.dataset.key], by = k.step || 1 / Math.max(1, k.stops() - 1);
    knobTo(el.dataset.key, clamp(k.n() + dir * by * (e.shiftKey || !k.step ? 1 : 5)));
    tell();
  });
  async function clear() {
    const all = Date.now() - ST.clearAt < 3000, pitch = ST.pitch;
    ST.clearAt = all ? 0 : Date.now();
    syncClear();
    if (!all) setTimeout(syncClear, 3050);
    await inLine("clear" + (all ? "-all" : ""), async () => {
      const now = await fresh();
      if (!now || !now.clip) return;  // no clip: nothing to clear
      const rows = now.pattern.rows.map((r) => (all || r.pitch === pitch ? {pitch: r.pitch, name: r.name, steps: r.steps.map(() => 0)} : r));
      await put(asWritten({...now.pattern, rows}));
    });
  }
  // Another length for the pattern: 1, 2 or 4 bars. The clip in Live is made that long (its notes stay; shortened,
  // the bars cut off go) when nothing else is in the way; when clips are, the bar says so and nothing is changed.
  async function setBars(n) {
    if (n === ST.bars || ST.loading || !ST.data) return;
    const old = ST.bars, at = spanKey();
    ST.loading = true; sync();
    const now = await fresh(), total = n * PER, fit = (list, cap) => list.concat(Array(total).fill(0)).slice(0, total).map((v) => (cap ? Math.min(v, total) : v));
    if (now && now.clip) {  // a clip of the old length is there: it is made the new length (a refusal shows as the bar's state)
      const rows = now.pattern.rows.map((r) => ({pitch: r.pitch, name: r.name, steps: fit(r.steps), ...(r.lengths ? {lengths: fit(r.lengths, true)} : {})}));
      await app().command("steps.write", {track: ST.track, bar: ST.bar, from_bars: old, src: SRC,
        pattern: {bars: n, steps_per_bar: PER, rows, length: Math.min(now.pattern.length, total), swing: now.pattern.swing || 0}}, undefined, true);
    }
    if (at !== spanKey() || !ST.open) return;
    ST.bars = n; ST.view = Math.min(ST.view, n - 1); ST.last = null;
    if (ST.length > n * PER) ST.length = n * PER;
    $("#song").__st = null;
    load();
    if (ST.looping) app().command("steps.loop", {bar: ST.bar, bars: n}, undefined, true);
  }
  // A tap on a pad: the step flips on the page at once, Live's answer settles it, a refusal puts it back (and the
  // app says why where it says every refusal).
  async function tap(k) {
    const row = rowOf(ST.pitch), step = ST.view * PER + k, at = `${ST.track}/${ST.bar}/${ST.bars}`;
    if (!ST.data || !row || blocked() || ST.loading) return;
    const pitch = row.pitch, was = row.steps[step];
    row.steps[step] = was ? 0 : ST.velocity; sync();
    const r = await app().command("steps.toggle", {track: ST.track, bar: ST.bar, bars: ST.bars, pitch, step, velocity: ST.velocity, length: ST.length, swing: ST.swing, src: SRC});
    const now = ST.open && at === `${ST.track}/${ST.bar}/${ST.bars}` ? rowOf(pitch) : null;  // the pattern may have been read again meanwhile
    if (!now) return;
    if (r.ok) { now.steps[step] = r.body.on ? r.body.velocity : 0; ST.last = r.body.on ? {pitch, step, at} : null; }
    else { now.steps[step] = was; if (r.body && r.body.blocked && r.body.blocked.length) ST.data.blocked = r.body.blocked; }
    sync();
  }
  function chooseSound(pitch) {
    if (!rowOf(pitch)) return;
    ST.pitch = pitch; fit(); sync(); tell();
  }
  // The sound before or after the chosen one.
  function stepSound(by) {
    const next = rows()[rows().indexOf(rowOf(ST.pitch)) + by];
    if (next) chooseSound(next.pitch);
  }
  function stepBar(by) {
    ST.bar = Math.max(1, ST.bar + by * ST.bars); ST.view = 0; ST.last = null;
    sync(); load();
    if (ST.looping) app().command("steps.loop", {bar: ST.bar, bars: ST.bars}, undefined, true);  // the loop follows the bar in hand
  }
  // The loop key: Live loops the pattern's bars, so it is heard going round with the song. The lit key again, and
  // closing Steps, put the loop back as it was.
  async function loopKey() {
    const st = app().S.state;
    if (looped()) {
      const was = ST.loopWas || {on: false, start: st.loop_span[0], length: st.loop_span[1]};
      ST.loopWas = null; ST.looping = false;
      return app().command("steps.loop", {was});
    }
    ST.looping = true;
    const r = await app().command("steps.loop", {bar: ST.bar, bars: ST.bars});
    if (r.ok && !ST.loopWas) ST.loopWas = r.body.was;
    else if (!r.ok) ST.looping = false;
  }
  // Live's playhead or loop moved. The step under the playhead is outlined while Live plays inside the pattern.
  function live() {
    const box = $("#steps");
    if (!box || !ST.open) return;
    const st = app().S.state, per = perBar(), start = (ST.bar - 1) * per;
    let k = -1;
    if (st && st.playing && st.pos >= start - 1e-6 && st.pos < start + ST.bars * per) {
      const step = Math.floor((st.pos - start) / (per / PER) + 1e-6);
      if (Math.floor(step / PER) === ST.view) k = step % PER;
    }
    if (k !== ST.ph) {
      ST.ph = k;
      box.querySelectorAll(".st-pad.ph").forEach((p) => p.classList.remove("ph"));
      if (k >= 0) box.querySelector(`.st-pad[data-k="${k}"]`).classList.add("ph");
    }
    const lk = box.querySelector('[data-st="loop"]'), on = looped();
    if (lk.classList.contains("on") !== on) { lk.classList.toggle("on", on); lk.setAttribute("aria-pressed", String(on)); }
  }
  // The app's {"t": "steps"} message. A pattern another hand changed (the MiniLab's pad, another page, an undo) is
  // read again; a focus another hand moved on this pattern (another sound, other values) is taken up.
  function message(m) {
    ST.focus = m.focus || null;
    if (!(ST.open || ST.painting) || m.src === SRC) return;
    if (m.edit) { if (m.edit.track === ST.track) load(true); return; }
    const f = m.focus;
    if (!ST.open || !f || f.track !== ST.track || f.bar !== ST.bar || f.bars !== ST.bars) return;
    if (rowOf(f.pitch)) ST.pitch = f.pitch;
    Object.assign(ST, {view: Math.min(f.view, ST.bars - 1), velocity: f.velocity, length: f.length});
    fit(); sync(); live();
  }

  function render() {
    if (ST.pick) return drawPicker();
    if (ST.open) return draw();
  }
  // A press on one of this file's keys (data-st). True when it was one.
  function click(t) {
    const what = t.dataset.st;
    if (!what) return false;
    if (what === "pick") pick();
    else if (what === "unpick") { ST.pick = null; app().renderSong(); }
    else if (what === "kit") makeTrack(t.dataset.kit);
    else if (what === "kitstep") { ST.pick.at += +t.dataset.by; fitPicker(); }
    else if (what === "open") open(app().S.song.sel);
    else if (what === "steps") open(ST.track, true);
    else if (what === "paint") { if (ST.painting && !ST.open) paintOff(); else paintOn(ST.open ? ST.track : app().S.song.sel); }
    else if (what === "erase") { ST.erase = !ST.erase; app().renderSong(); }
    else if (what === "close") close();
    else if (what === "bar") stepBar(+t.dataset.by);
    else if (what === "sound") chooseSound(+t.dataset.pitch);
    else if (what === "snd") stepSound(+t.dataset.by);
    else if (what === "pad") tap(+t.dataset.k);
    else if (what === "loop") loopKey();
    else if (what === "bars") setBars(+t.dataset.v);
    else if (what === "view") { ST.view = +t.dataset.v; sync(); live(); tell(); }
    else if (what === "clear") clear();
    return true;
  }
  // The page goes away with Steps open: the app is told nothing is in hand, so no pad is left mapped to a pattern.
  window.addEventListener("pagehide", () => {
    if (ST.open && navigator.sendBeacon) navigator.sendBeacon("/api/command", new Blob([JSON.stringify({kind: "steps.focus", args: {src: SRC}})], {type: "application/json"}));
  });
  const refit = () => { if (ST.pick) fitPicker(); else if (ST.open) fit(); };
  if (window.ResizeObserver) new ResizeObserver(refit).observe($("#song")); else window.addEventListener("resize", refit);

  window.zpktSteps = {open, close, render, click, shown, songKeys, newKey, message, live, painting, lane, songSel, state: ST, src: SRC};
  if (app() && app().S.song.loaded) app().renderSong();  // the Song was drawn before this file arrived: its keys are drawn now
})();
