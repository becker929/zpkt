// The one tab bar of the app: Desk, Song, Options, Ask, the same on every page. Served at /app/shell/nav.js.
// A page has <nav id="tabs" data-current="desk|song|options|ask"></nav> and loads this file after it.
// On /app/ the first three are buttons (data-t) that the shell switches in place; on any other page they are links
// to /app/#desk, /app/#song and /app/#options. Ask is always a link to /app/ask/.
(function () {
  "use strict";
  const TABS = [
    ["desk", "Desk", '<circle cx="8" cy="8" r="3.5"/><circle cx="16" cy="16" r="3.5"/><path d="M13 7h7M4 17h5"/>'],
    ["song", "Song", '<path d="M4 7h9M4 12h16M4 17h11"/>'],
    ["options", "Options", '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5" fill="currentColor"/>'],
    ["ask", "Ask", '<path d="M4 5h16v11H10l-5 4v-4H4z"/>'],
  ];
  const IDS = {desk: "tab-desk", song: "tab-song", options: "topts", ask: "task"};  // the last two are the ids the shell always had
  const nav = document.getElementById("tabs");
  if (!nav) return;
  const inPlace = /^\/app\/?$/.test(location.pathname);
  const icon = d => `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
  nav.setAttribute("aria-label", "Tabs");
  nav.innerHTML = TABS.map(([id, name, d]) =>
    id !== "ask" && inPlace
      ? `<button type="button" data-t="${id}" id="${IDS[id]}">${icon(d)}<span>${name}</span></button>`
      : `<a data-t="${id}" id="${IDS[id]}" href="${id === "ask" ? "/app/ask/" : "/app/#" + id}">${icon(d)}<span>${name}</span></a>`).join("");

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
  window.zpktNav = {set, inPlace};
})();
