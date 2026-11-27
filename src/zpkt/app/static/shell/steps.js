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
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const app = () => window.zpkt;
  const PER = 16;  // the steps of a bar
  const ROW_MIN = 24;  // px: the least height of an overview row; fewer rows show when they do not fit
  const ST = {open: false, pick: null, track: "", bar: 1, bars: 1, view: 0, pitch: null, data: null, at: 0, per: 8,
              seq: 0, loading: false, velocity: 100, length: 1, swing: 0};
  const icon = (n, size = 18) => `<svg width="${size}" height="${size}" aria-hidden="true"><use href="#i-${n}"/></svg>`;
  const esc = (t) => app().esc(t);
  const trackOf = (name) => { const v = app().S.song.view; return (v && v.tracks.find((t) => t.name === name)) || null; };
  const rows = () => (ST.data ? ST.data.pattern.rows : []);
  const rowOf = (pitch) => rows().find((r) => r.pitch === pitch) || null;
  const blocked = () => !!(ST.data && ST.data.blocked && ST.data.blocked.length);
  const shown = () => ST.open || !!ST.pick;

  // ---- the Song's own keys ------------------------------------------------------------------------------------------
  function songKeys(t) {
    return t && t.midi ? `<button class="key sm" type="button" data-st="open" aria-label="Steps: ${esc(t.name)}">${icon("steps")}Steps</button>` : "";
  }
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
  function open(name) {
    if (!trackOf(name)) return;
    Object.assign(ST, {open: true, pick: null, track: name, bar: startBar(), bars: 1, view: 0, pitch: null, data: null, at: 0});
    render();
    load();
  }
  function close() {
    ST.open = false; ST.pick = null; ST.data = null; ST.seq++;
    app().renderSong();
  }
  // Read the pattern at the bar in hand. A reply to a question that is no longer the newest is dropped.
  async function load() {
    const mine = ++ST.seq, z = app(), v = z.S.song.view;
    ST.loading = true; sync();
    const r = await z.command("steps.read", {track: ST.track, bar: ST.bar, bars: ST.bars, swing: ST.swing, total_bars: Math.max(1, (v && v.bars) || 0, z.songOf().bars || 0)});
    if (mine !== ST.seq || !ST.open) return;
    ST.loading = false;
    if (!r.ok) { ST.data = null; return render(); }
    ST.data = r.body;
    if (!rowOf(ST.pitch)) ST.pitch = rows().length ? rows()[0].pitch : null;
    ST.view = Math.min(ST.view, ST.bars - 1);
    render();
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
    setSong(`<div id="steps" data-track="${esc(ST.track)}">
      <div class="st-bar"><span class="sn">${t.color ? `<i class="cd" style="background:${esc(t.color)}"></i>` : ""}<b>${esc(ST.track)}</b></span>
        <button class="key sm" type="button" data-st="bar" data-by="-1" aria-label="Bar before"><svg class="back" width="18" height="18" aria-hidden="true"><use href="#i-more"/></svg></button>
        <span class="st-barn" id="st-barn" role="status"></span>
        <button class="key sm" type="button" data-st="bar" data-by="1" aria-label="Bar after">${icon("more")}</button>
        <button class="key sm" type="button" data-st="close" aria-label="Close Steps">${icon("x")}</button></div>
      <div class="st-ov" id="st-ov" role="group" aria-label="Sounds">${ov}</div>${pager("st-pgs", "sndstep", "Sounds")}
      <div class="st-ml"><div class="st-head"><b id="st-name"></b></div>
        <span class="tag">pads A</span>${pads(0)}<span class="tag">pads B</span>${pads(8)}</div></div>`);
    fit(); sync();
  }
  // As many sound rows as the height holds (8 at most); more are a page away. The page with the chosen sound shows.
  function fit() {
    const ov = $("#st-ov"), bar = $("#st-pgs");
    if (!ov || !bar || $("#song").hidden) return;
    const all = [...ov.children], count = (h) => Math.max(1, Math.min(8, Math.floor((h + 2) / (ROW_MIN + 2))));
    all.forEach((r) => { r.hidden = true; });  // measured empty: the rows give the box no height of their own
    bar.hidden = true;
    let per = count(ov.clientHeight);
    if (all.length > per) { bar.hidden = false; per = count(ov.clientHeight); }
    const parts = Math.max(1, Math.ceil(all.length / per));
    if (ST.per !== per) { ST.per = per; const at = all.findIndex((r) => +r.dataset.pitch === ST.pitch); ST.at = at < 0 ? 0 : Math.floor(at / per); }
    ST.at = Math.max(0, Math.min(parts - 1, ST.at));
    all.forEach((r, i) => { r.hidden = Math.floor(i / per) !== ST.at; });
    setPager(bar, ST.at, per, all.length);
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
    for (const el of box.querySelectorAll(".st-row")) {
      const row = rowOf(+el.dataset.pitch), sel = +el.dataset.pitch === ST.pitch;
      el.classList.toggle("sel", sel); el.setAttribute("aria-pressed", String(sel));
      el.querySelectorAll(".c").forEach((c, k) => c.classList.toggle("on", !!(row && row.steps[from + k])));
    }
    const mine = rowOf(ST.pitch);
    $("#st-name").textContent = mine ? mine.name : "";
    for (const pad of box.querySelectorAll(".st-pad")) {
      const v = mine ? mine.steps[from + +pad.dataset.k] : 0;
      pad.classList.toggle("on", !!v); pad.classList.toggle("soft", v > 0 && v < 80);
      pad.setAttribute("aria-pressed", String(!!v));
      pad.disabled = off || !mine || !ST.data;
    }
  }
  // A tap on a pad: the step flips on the page at once, Live's answer settles it, a refusal puts it back (and the
  // app says why where it says every refusal).
  async function tap(k) {
    const d = ST.data, row = rowOf(ST.pitch), step = ST.view * PER + k;
    if (!d || !row || blocked() || ST.loading) return;
    const was = row.steps[step];
    row.steps[step] = was ? 0 : ST.velocity; sync();
    const r = await app().command("steps.toggle", {track: ST.track, bar: ST.bar, bars: ST.bars, pitch: row.pitch, step, velocity: ST.velocity, length: ST.length, swing: ST.swing});
    if (r.ok) row.steps[step] = r.body.on ? r.body.velocity : 0;
    else { row.steps[step] = was; if (r.body && r.body.blocked && r.body.blocked.length) d.blocked = r.body.blocked; }
    if (d === ST.data) sync();
  }
  function chooseSound(pitch) {
    if (!rowOf(pitch)) return;
    ST.pitch = pitch; sync();
  }
  function stepBar(by) {
    ST.bar = Math.max(1, ST.bar + by * ST.bars); ST.view = 0;
    sync(); load();
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
    else if (what === "close") close();
    else if (what === "bar") stepBar(+t.dataset.by);
    else if (what === "sound") chooseSound(+t.dataset.pitch);
    else if (what === "sndstep") { ST.at += +t.dataset.by; fit(); }
    else if (what === "pad") tap(+t.dataset.k);
    return true;
  }
  const refit = () => { if (ST.pick) fitPicker(); else if (ST.open) fit(); };
  if (window.ResizeObserver) new ResizeObserver(refit).observe($("#song")); else window.addEventListener("resize", refit);

  window.zpktSteps = {open, close, render, click, shown, songKeys, newKey, state: ST};
})();
