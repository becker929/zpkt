// The one tab bar of the app: Desk, Song, Monitor, Ask, the same on every page. Served at /app/shell/nav.js.
// A page has <nav id="tabs" data-current="desk|song|ask"></nav> and loads this file after it.
// On /app/ the three are buttons (data-t) that the shell switches in place; on any other page they are links to
// /app/#desk, /app/#song and /app/#ask.
//
// Ask is the page /app/ask/ shown in a frame inside <div id="ask" hidden> on /app/, so the Hear bar, the transport and
// Listen stay where they are while I chat. The frame is made the first time Ask is shown and kept after that: an
// answer goes on arriving while the Desk is showing, and the Ask tab then carries a mark (data-mark="busy" while the
// agent works, "new" once it has answered) until Ask is shown again. The frame talks to this file with postMessage:
// {zpktAsk: {state}} and {zpktAsk: {go: "#page=<id>"}}, which changes the address here with no reload.
(function () {
  "use strict";
  const TABS = [
    ["desk", "Desk", '<circle cx="8" cy="8" r="3.5"/><circle cx="16" cy="16" r="3.5"/><path d="M13 7h7M4 17h5"/>'],
    ["song", "Song", '<path d="M4 7h9M4 12h16M4 17h11"/>'],
    ["monitor", "Monitor", '<path d="M3 16c3 0 3-9 6-9s3 6 6 6 3-3 6-3"/><path d="M3 20h18"/>'],
    ["ask", "Ask", '<path d="M4 5h16v11H10l-5 4v-4H4z"/>'],
  ];
  const IDS = {desk: "tab-desk", song: "tab-song", monitor: "tab-monitor", ask: "task"};
  const nav = document.getElementById("tabs");
  if (!nav) return;
  const inPlace = /^\/app\/?$/.test(location.pathname);
  const icon = d => `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
  nav.setAttribute("aria-label", "Tabs");
  nav.innerHTML = TABS.map(([id, name, d]) =>
    inPlace
      ? `<button type="button" data-t="${id}" id="${IDS[id]}">${icon(d)}<span>${name}</span></button>`
      : `<a data-t="${id}" id="${IDS[id]}" href="/app/#${id}">${icon(d)}<span>${name}</span></a>`).join("");

  function set(current) {
    nav.dataset.current = current;
    for (const el of nav.children) {
      const on = el.dataset.t === current;
      el.classList.toggle("on", on);
      if (on) el.setAttribute("aria-current", "page"); else el.removeAttribute("aria-current");
    }
  }
  set(nav.dataset.current || "desk");

  // Where the bar sits: last on a phone, first from 700 px up. A page that wrote data-at itself keeps it.
  if (!nav.dataset.at) {
    const wide = window.matchMedia("(min-width:700px)");
    const place = () => { nav.dataset.at = wide.matches ? "top" : "bottom"; };
    wide.addEventListener("change", place);
    place();
  }

  // ---- Ask in place (on /app/ only) ----
  const host = inPlace ? document.getElementById("ask") : null;
  const tab = document.getElementById(IDS.ask);
  const app = document.getElementById("app");
  let frame = null, working = false;   // working: the agent is in a turn
  const shown = () => !!host && !host.hidden;
  function mark(m) {
    if (m) tab.dataset.mark = m; else delete tab.dataset.mark;
    tab.setAttribute("aria-label", m === "new" ? "Ask, new answer" : m === "busy" ? "Ask, working" : "Ask");
  }
  /** Show or hide the chat. The app's own tab switch calls this with true for Ask and false for any other tab. */
  function ask(on) {
    if (!host) return;
    if (on && !frame) {
      frame = document.createElement("iframe");
      frame.title = "Ask"; frame.src = "/app/ask/?embedded=1";
      host.append(frame);
    }
    const was = shown();
    host.hidden = !on;
    if (on) { mark(""); if (!was) frame.contentWindow?.postMessage({zpktAsk: "shown"}, location.origin); }
    else if (was && working) mark("busy");
    fit();
  }
  // A phone with its keyboard up, or any short view: the app is as tall as what can be seen, and with Ask showing the
  // Hear bar keeps only its first row (#app.short), so the composer sits above the tab bar with room to read.
  function fit() {
    if (!app) return;
    const vv = window.visualViewport, h = vv ? vv.height : innerHeight;
    const covered = shown() && !!vv && vv.scale < 1.01 && innerHeight - h > 1;   // not a pinch zoom
    app.classList.toggle("short", shown() && h < 600 && innerWidth < 700);
    app.style.height = covered ? h + "px" : "";
    app.style.transform = covered && vv.offsetTop > 0 ? `translateY(${vv.offsetTop}px)` : "";
  }
  if (host) {
    window.addEventListener("message", e => {
      const m = e.data && e.data.zpktAsk;
      if (!m || e.origin !== location.origin || !frame || e.source !== frame.contentWindow) return;
      if (typeof m.go === "string" && /^#[\w.=%\-]{0,140}$/.test(m.go)) {
        // the address changes in this document; the same address again still means "go there"
        if (location.hash === m.go) window.dispatchEvent(new HashChangeEvent("hashchange")); else location.hash = m.go;
      }
      else if (m.state === "busy" || m.state === "done") { working = m.state === "busy"; mark(shown() ? "" : working ? "busy" : "new"); }
      else if (m.state === "idle") { working = false; mark(""); }
    });
    if (window.visualViewport) for (const ev of ["resize", "scroll"]) window.visualViewport.addEventListener(ev, fit);
    window.addEventListener("resize", fit);
  }
  /** Another song is open (zpkt.app.songs): the chat shows that song's conversation. Not while the agent works. */
  function reloadAsk() {
    if (frame && !working) frame.src = "/app/ask/?embedded=1";
  }
  window.zpktNav = {set, inPlace, ask, reloadAsk};
})();
