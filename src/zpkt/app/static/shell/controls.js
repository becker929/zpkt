// A panel: one MiniLab 3 page as a map of the controller. Served at /app/shell/controls.js; the styles are
// controls.css. A classic script (not a module): load it before the page's own script, then use window.zpktControls.
//
// It only draws. All 20 slots are always there, each in its physical place: the 8 knobs (k1-k8), the 4 faders
// (f1-f4), the 8 pads (b1-b8). The page hands over what each slot holds and does the talking to the app itself.
// The knob, the fader and the pad are the chat's drawings (static/ask/zpkt/draw.js), with the value as a place 0..1.
//
// A slot model: {slot, state, label, shown, n, key, hw, by, group, tint, why, range, steps, chg, flash}
//   state  "live" (takes touch), "macro" (moved from the MiniLab only), "missing" (the open set lacks its target),
//          "off" (nothing is mapped). Left out means "off".
//   n      its place, 0 to 1; shown: the value as text; key: its state key; hw: the MiniLab page it is on
//   by     "key" or "slot": how a pad is toggled (the page reads it back from data-by)
//   group  a small caption over the control; tint 0 or 1; why: the reason it is greyed
//   range  [low, high] places worth playing; steps: how many stops a knob has (a choice), 0 for a smooth one
(function () {
  "use strict";
  const KNOBS = ["k1", "k2", "k3", "k4", "k5", "k6", "k7", "k8"], FADERS = ["f1", "f2", "f3", "f4"];
  const PADS = ["b1", "b2", "b3", "b4", "b5", "b6", "b7", "b8"];
  const KIND = {k: "knob", f: "fader", b: "pad"}, WORD = {k: "Knob", f: "Fader", b: "Pad"};
  const kindOf = (slot) => KIND[slot[0]];
  /** What the hardware calls a slot: "Knob 6", "Fader 2", "Pad 3". */
  const hwName = (slot) => `${WORD[slot[0]]} ${slot.slice(1)}`;
  const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (ch) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[ch]));
  const clamp = (n) => Math.max(0, Math.min(1, Number.isFinite(+n) ? +n : 0));
  const pct = (n) => Math.round(clamp(n) * 100);

  // The knob's metal, one copy for the whole document: every knob's <svg> refers to these gradients.
  function ensureDefs() {
    if (document.getElementById("zk-defs")) return;
    const stop = (o, c) => `<stop offset="${o}" style="stop-color:var(${c})"/>`;
    document.body.insertAdjacentHTML("afterbegin", `<svg id="zk-defs" width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
      <linearGradient id="zk-cap" x1="0" y1="0" x2="1" y2="1">${stop(0, "--zk-1")}${stop(0.5, "--zk-2")}${stop(1, "--zk-3")}</linearGradient>
      <linearGradient id="zk-face" x1="0" y1="0" x2="1" y2="1">${stop(0, "--zk-3")}${stop(0.45, "--zk-2")}${stop(1, "--zk-1")}</linearGradient></defs></svg>`);
  }

  const A0 = Math.PI * 0.75, A1 = Math.PI * 2.25, CX = 34, CY = 36;
  const at = (n) => A0 + clamp(n) * (A1 - A0);
  function arc(r, a0, a1) {
    const p = (a) => [CX + r * Math.cos(a), CY + r * Math.sin(a)];
    const [x0, y0] = p(a0), [x1, y1] = p(a1);
    return `M${x0.toFixed(2)} ${y0.toFixed(2)}A${r} ${r} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
  }
  /** The knob as an <svg>. o.off: a flat blank with no arc; o.range: [low, high]; o.steps: tick marks for a choice. */
  function knob(n, o = {}) {
    const head = '<svg viewBox="0 0 68 62" aria-hidden="true" focusable="false">';
    if (o.off) return `${head}<path class="zk-well" d="${arc(27, A0, A1)}"/><circle class="zk-flat" cx="${CX}" cy="${CY}" r="20"/></svg>`;
    const a = at(n);
    const line = (r0, r1, ang, cls) => `<line class="${cls}" x1="${(CX + r0 * Math.cos(ang)).toFixed(2)}" y1="${(CY + r0 * Math.sin(ang)).toFixed(2)}" x2="${(CX + r1 * Math.cos(ang)).toFixed(2)}" y2="${(CY + r1 * Math.sin(ang)).toFixed(2)}"/>`;
    let ticks = "";
    if (o.steps > 1 && o.steps <= 12) for (let i = 0; i < o.steps; i++) ticks += line(30.5, 33, at(i / (o.steps - 1)), "zk-tick");
    const rg = o.range ? `<path class="zk-rg rg" d="${arc(32, at(o.range[0]), Math.max(at(o.range[0]) + 0.02, at(o.range[1])))}"/>` : "";
    return `${head}<path class="zk-well" d="${arc(27, A0, A1)}"/><path class="zk-arc" d="${arc(27, A0, Math.max(A0 + 0.001, a))}"/>${rg}${ticks}` +
      `<circle class="zk-sh" cx="${CX}" cy="${CY + 1.8}" r="20.6"/><circle class="zk-cap" cx="${CX}" cy="${CY}" r="20"/>` +
      `<circle class="zk-knurl" cx="${CX}" cy="${CY}" r="18.7"/><circle class="zk-face" cx="${CX}" cy="${CY}" r="15.8"/>` +
      `<circle class="zk-top" cx="${CX}" cy="${CY}" r="13.8"/>${line(5, 12.5, a, "zk-ptr")}</svg>`;
  }
  /** The fader's inside: the slot, quarter marks, the lime fill and the cap. */
  function fader(n, o = {}) {
    const p = o.off ? 0 : clamp(n) * 100;
    let marks = "";
    for (let i = 0; i <= 4; i++) marks += `<i class="fk" style="top:${i * 25}%"></i>`;
    const rg = o.range && !o.off ? `<b class="rg" style="bottom:${pct(o.range[0])}%;height:${Math.max(2, pct(o.range[1]) - pct(o.range[0]))}%"></b>` : "";
    return `<span class="fx" aria-hidden="true">${marks}<i class="ft"></i>${rg}<i class="ff" style="height:${p.toFixed(1)}%"></i><i class="fc" style="bottom:${p.toFixed(1)}%"></i></span>`;
  }

  /** One slot as HTML. */
  function slot(m) {
    const kind = kindOf(m.slot), name = hwName(m.slot), state = m.state || "off";
    const n = clamp(m.n), on = kind === "pad" && state !== "off" && state !== "missing" && n >= 0.5;
    const cls = ["ctl", "mc", kind, state, m.tint ? "t1" : "t0", on ? "on" : "", m.chg ? "chg" : "", m.flash ? "flash" : ""].filter(Boolean).join(" ");
    const data = `data-slot="${m.slot}" data-state="${state}" data-key="${esc(m.key || "")}" data-hw="${m.hw ?? ""}" data-by="${m.by || "key"}" data-n="${n}" data-steps="${m.steps || 0}" data-range="${m.range ? m.range.join(",") : ""}"`;
    const cap = m.group || m.caps ? `<div class="g">${esc(m.group || "")}</div>` : "";  // caps: keep the row level
    const spoken = (m.group ? m.group + ": " : "") + (m.label || name);
    if (state === "off") {
      const face = kind === "pad" ? `<div class="w" role="img" aria-label="${name}: not mapped"><span>${name}</span></div>`
        : `<div class="w" role="img" aria-label="${name}: not mapped">${kind === "knob" ? knob(0, {off: true}) : fader(0, {off: true})}</div><div class="v"></div><div class="l">${name}</div>`;
      return `<div class="${cls}" ${data} aria-disabled="true" title="${name}: not mapped">${cap}${face}</div>`;
    }
    if (state === "missing") {
      const why = m.why || "not in this set";
      const face = kind === "pad" ? `<div class="w" role="img" aria-label="${esc(spoken)}: not in this set"><span>${esc(m.label)}</span></div>`
        : `<div class="w" role="img" aria-label="${esc(spoken)}: not in this set">${kind === "knob" ? knob(0, {off: true}) : fader(0, {off: true})}</div><div class="v">not in this set</div><div class="l">${esc(m.label)}</div>`;
      return `<div class="${cls}" ${data} aria-disabled="true" title="${esc(why)}">${cap}${face}</div>`;
    }
    const live = state === "live", note = live ? "" : ' title="A macro: turn it on the MiniLab."';
    if (kind === "pad") {
      const face = live ? `<button class="w" data-mpad aria-pressed="${on}" aria-label="${esc(spoken)}"><span>${esc(m.label)}</span></button>`
        : `<div class="w" role="img" aria-label="${esc(spoken)}"><span>${esc(m.label)}</span></div>`;
      return `<div class="${cls}" ${data}${note}>${cap}${face}</div>`;
    }
    const draw = kind === "knob" ? knob(n, m) : fader(n, m);
    const aria = live ? `role="slider" tabindex="0" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct(n)}" aria-valuetext="${esc(m.shown ?? "")}"` : 'role="img"';
    return `<div class="${cls}" ${data}${note}>${cap}<div class="w" ${aria} aria-label="${esc(spoken)}">${draw}</div><div class="v">${esc(m.shown ?? "")}</div><div class="l" title="${esc(m.label)}">${esc(m.label)}</div></div>`;
  }

  /** The whole panel. `slots` is a list or a {slot: model} map; a slot it lacks is drawn unmapped. `attrs` goes on
      the panel's <section> (the page puts id and data-stale there). */
  function panel(slots, attrs = "") {
    ensureDefs();
    const by = {};
    for (const m of Array.isArray(slots) ? slots : Object.values(slots)) if (m && m.slot) by[m.slot] = m;
    const caps = Object.values(by).some((m) => m.group);  // one slot has a group caption: every slot keeps its line
    const block = (cls, ids) => `<div class="${cls}">${ids.map((id) => slot({...(by[id] || {slot: id, state: "off"}), caps})).join("")}</div>`;
    return `<div class="mlpw"><section class="mlp" aria-label="MiniLab 3 layout" ${attrs}>${block("mk", KNOBS)}${block("mf", FADERS)}${block("mp mp1", PADS.slice(0, 4))}${block("mp mp2", PADS.slice(4))}</section></div>`;
  }

  /** Move one drawn knob or fader to place n without redrawing the panel (while it is dragged). */
  function set(el, n) {
    const w = el.querySelector(".w");
    if (!w) return;
    if (el.classList.contains("knob")) {
      w.innerHTML = knob(n, {steps: +el.dataset.steps, range: el.dataset.range ? el.dataset.range.split(",").map(Number) : null});
    } else if (el.classList.contains("fader")) {
      const p = (clamp(n) * 100).toFixed(1) + "%";
      w.querySelector(".ff").style.height = p;
      w.querySelector(".fc").style.bottom = p;
    }
    if (w.getAttribute("role") === "slider") w.setAttribute("aria-valuenow", pct(n));
  }

  window.zpktControls = {KNOBS, FADERS, PADS, SLOTS: [...KNOBS, ...FADERS, ...PADS], kindOf, hwName, knob, fader, slot, panel, set};
})();
