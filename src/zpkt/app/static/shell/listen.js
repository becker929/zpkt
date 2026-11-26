// Listen: hear what Live is playing, in this browser.
//
// Self-contained. On a page that has <span id="listen"></span> it draws one button there. A tap starts the sound
// (browsers only let sound start from a tap). It plays Live's own output and changes nothing in it: no EQ, no
// effects, no gain. Raw PCM comes over a streamed fetch and plays through an AudioWorklet that keeps a short buffer
// and throws away old sound when it falls behind. Where that cannot work (no AudioWorklet, no streamed fetch, a page
// that is not served securely) it plays an MP3 stream in an <audio> element, which is a second or more late.
//
// The sample rate is the Mac's capture's, not a fixed one: 44100 from the Live device on a 44.1 kHz set, 48000 from
// the screen capture. The stream says its rate in its X-Audio-Format header, and the sound is played at exactly that
// rate, so nothing is resampled here. A browser that will not open its output at that rate gets the MP3 stream.
//
// The choice is remembered (localStorage "zpkt.listen"). After a move to another page the button shows "resume" and
// the first tap anywhere on the page starts the sound again.

const BASE = '/app/listen';
const KEY = 'zpkt.listen';
const USUAL_RATE = 48000; // only a first guess, until the status or the stream has said the real rate
const TARGET_MS = 70; // sound kept in hand before playing (it grows, up to 250, each time the buffer runs dry)
const MAX_MS = 220; // more than this is late: drop back to the target

const ICON =
  '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" ' +
  'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 14v-2a8 8 0 0 1 16 0v2"/>' +
  '<rect x="3" y="14" width="4.5" height="6.5" rx="1.6"/><rect x="16.5" y="14" width="4.5" height="6.5" rx="1.6"/></svg>';

const CSS = `
:where(.lsn){position:relative;display:inline-flex;align-items:center;justify-content:center;gap:6px;min-width:44px;
  min-height:44px;padding:0 10px;border-radius:12px;border:1px solid var(--cl,#8886);background:none;color:inherit;
  font:inherit;font-size:13px;cursor:pointer;white-space:nowrap;-webkit-tap-highlight-color:transparent}
.lsn[data-state=on]{border-color:var(--now,#2a9d5c);color:var(--now,#2a9d5c)}
.lsn[data-state=unavailable]{opacity:.55}
.lsn[data-state=connecting] svg{animation:lsn-pulse 1s ease-in-out infinite}
@keyframes lsn-pulse{50%{opacity:.35}}
.lsn .lsn-lv{display:none;width:4px;height:18px;border-radius:2px;background:var(--cl,#8884);overflow:hidden;
  position:relative}
.lsn[data-state=on] .lsn-lv{display:block}
.lsn .lsn-lv i{position:absolute;left:0;right:0;bottom:0;height:100%;background:currentColor;transform-origin:bottom;
  transform:scaleY(0);transition:transform .09s linear}
.lsn .lsn-dot{display:none;width:7px;height:7px;border-radius:50%;background:var(--pin,#d98a00)}
.lsn[data-resume] .lsn-dot{display:block}
.lsn-why{position:fixed;z-index:1000;max-width:min(300px,calc(100vw - 24px));padding:10px 12px;border-radius:12px;
  background:var(--panel,#fff);color:var(--ink,#111);border:1px solid var(--line,#8888);font-size:13px;line-height:1.35;
  box-shadow:0 6px 24px #0004}
@media (prefers-color-scheme:dark){.lsn-why{background:var(--panel,#1c1c1e);color:var(--ink,#eee)}}
`;

// The worklet: a ring of stereo frames. It only moves samples from the network to the output.
const WORKLET = `
class ZpktListen extends AudioWorkletProcessor {
  constructor(o) {
    super();
    const p = o.processorOptions;
    this.size = sampleRate * 2;
    this.l = new Float32Array(this.size); this.r = new Float32Array(this.size);
    this.w = 0; this.rd = 0; this.have = 0;
    this.target = Math.round(sampleRate * p.target / 1000); this.max = Math.round(sampleRate * p.max / 1000);
    this.filling = true; this.peak = 0; this.n = 0; this.under = 0; this.drops = 0; this.sum = 0; this.blocks = 0;
    this.port.onmessage = e => this.push(new Int16Array(e.data));
  }
  push(a) {
    const n = a.length >> 1;
    for (let i = 0; i < n; i++) {
      this.l[this.w] = a[2 * i] / 32768; this.r[this.w] = a[2 * i + 1] / 32768;
      this.w = (this.w + 1) % this.size;
    }
    this.have += n;
    if (this.have > this.max) {             // late: jump forward to the newest sound
      const cut = this.have - this.target;
      this.rd = (this.rd + cut) % this.size; this.have -= cut; this.drops++;
    }
  }
  process(_, outs) {
    const L = outs[0][0], R = outs[0][1] || outs[0][0], n = L.length;
    if (this.filling && this.have >= this.target) this.filling = false;
    if (!this.filling && this.have < n) {   // ran dry: the network is uneven, so keep a little more in hand
      this.filling = true; this.under++;
      this.target = Math.min(Math.round(this.target * 1.5), Math.round(sampleRate * 0.25));
      this.max = this.target + Math.round(sampleRate * 0.15);
    }
    if (!this.filling) {
      for (let i = 0; i < n; i++) {
        const a = this.l[this.rd], b = this.r[this.rd];
        L[i] = a; R[i] = b;
        const m = Math.max(Math.abs(a), Math.abs(b)); if (m > this.peak) this.peak = m;
        this.rd = (this.rd + 1) % this.size;
      }
      this.have -= n;
    }
    this.sum += this.have; this.blocks++;
    this.n += n;
    if (this.n >= sampleRate / 10) {
      this.port.postMessage({ peak: this.peak, ms: 1000 * this.sum / this.blocks / sampleRate, under: this.under, drops: this.drops });
      this.peak = 0; this.n = 0; this.sum = 0; this.blocks = 0;
    }
    return true;
  }
}
registerProcessor('zpkt-listen', ZpktListen);
`;

const remembered = () => { try { return localStorage.getItem(KEY) === 'on'; } catch { return false; } };
const remember = on => { try { localStorage.setItem(KEY, on ? 'on' : 'off'); } catch { /* private mode */ } };
const forced = () => { try { return localStorage.getItem(KEY + '.mode') || ''; } catch { return ''; } };

function mount(slot) {
  if (!document.getElementById('lsn-css')) {
    const st = document.createElement('style');
    st.id = 'lsn-css';
    st.textContent = CSS;
    document.head.appendChild(st);
  }
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'lsn key';
  btn.innerHTML = ICON + '<span class="lsn-lv"><i></i></span><span class="lsn-dot"></span>';
  const bar = btn.querySelector('.lsn-lv i');
  slot.replaceChildren(btn);

  let state = 'off'; // off | connecting | on | unavailable
  let reason = '';
  let ctx = null, node = null, abort = null, audio = null, why = null, tries = 0, quiet = null;
  let rate = 0; // the rate the Mac last said (status or stream); 0 until it has
  const stats = { mode: '', ms: 0, under: 0, drops: 0, peak: 0, bytes: 0, rate: 0 };
  window.zpktListen = { stats, get state() { return state; }, get reason() { return reason; } };

  const LABEL = {
    off: 'Listen: hear Live in this browser',
    connecting: 'Listen: connecting',
    on: 'Listening to Live. Tap to stop',
    unavailable: 'Listen is not available. Tap to see why',
  };
  function set(next) {
    state = next;
    btn.dataset.state = next;
    btn.setAttribute('aria-pressed', String(next === 'on' || next === 'connecting'));
    const resume = next === 'off' && remembered();
    btn.toggleAttribute('data-resume', resume);
    btn.title = resume ? 'Listen was on. Tap to resume' : LABEL[next];
    btn.setAttribute('aria-label', btn.title);
    if (next !== 'on') bar.style.transform = 'scaleY(0)';
  }
  function level(peak) {
    stats.peak = peak;
    const db = peak > 0 ? 20 * Math.log10(peak) : -90;
    bar.style.transform = `scaleY(${Math.max(0, Math.min(1, (db + 54) / 54)).toFixed(3)})`;
  }
  function explain(text) {
    hideWhy();
    why = document.createElement('div');
    why.className = 'lsn-why';
    why.setAttribute('role', 'status');
    why.textContent = text;
    document.body.appendChild(why);
    const b = btn.getBoundingClientRect(), w = why.getBoundingClientRect();
    const left = Math.max(12, Math.min(innerWidth - w.width - 12, b.left + b.width / 2 - w.width / 2));
    const above = b.top - w.height - 8;
    why.style.left = left + 'px';
    why.style.top = (above >= 8 ? above : Math.min(innerHeight - w.height - 8, b.bottom + 8)) + 'px';
    setTimeout(() => document.addEventListener('click', hideWhy, { once: true }), 0);
  }
  function hideWhy() { if (why) { why.remove(); why = null; } }

  async function status() {
    const r = await fetch(BASE + '/status', { cache: 'no-store' });
    if (!r.ok) throw new Error('status ' + r.status);
    const s = await r.json();
    const said = s.format && Number(s.format.rate);
    if (said > 0) rate = said;
    return s;
  }
  // The rate of a stream: its header says it; failing that the status does.
  async function rateOf(res) {
    const m = /rate=(\d+)/.exec(res.headers.get('X-Audio-Format') || '');
    if (m) return Number(m[1]);
    try { await status(); } catch { /* keep what we have */ }
    return rate || USUAL_RATE;
  }

  function hangUp() {
    if (abort) { abort.abort(); abort = null; }
    clearTimeout(quiet);
  }
  function teardown() {
    hangUp();
    dropContext();
    if (audio) { audio.pause(); audio.removeAttribute('src'); audio.load(); audio = null; }
  }
  function dropContext() {
    if (node) { node.port.onmessage = null; node.disconnect(); node = null; }
    if (ctx) { ctx.close().catch(() => {}); ctx = null; }
  }
  function stop(keep) {
    teardown();
    if (!keep) remember(false);
    set('off');
  }
  function fail(text) {
    teardown();
    reason = text;
    set('unavailable');
    explain(text);
  }
  function retry() {
    // The stream ended while we were on (the network dropped, the capture restarted). The AudioContext or the
    // <audio> element that a tap unlocked is kept, so the sound can come back without another tap.
    hangUp();
    if (++tries > 6) return fail('The sound from the Mac stopped and did not come back. Tap to try again.');
    set('connecting');
    quiet = setTimeout(async () => {
      try {
        const s = await status();
        if (!s.available) return fail(s.reason);
        if (node) await connect();
        else if (audio) { audio.src = BASE + '/stream.mp3?t=' + Date.now(); await audio.play(); }
        else set('off');
      } catch (err) {
        if (err.plain) return fail(err.message);
        if (err.rate && state === 'connecting') {
          // The capture came back at a rate this browser will not play: the MP3 stream plays at any rate.
          try { return await startMp3(); } catch { teardown(); }
        }
        if (state === 'connecting') retry();
      }
    }, 500 * tries);
  }

  const canWorklet = () =>
    forced() !== 'mp3' && window.isSecureContext && 'AudioWorkletNode' in window &&
    'ReadableStream' in window && 'body' in Response.prototype;
  const within = (promise, ms) =>
    Promise.race([promise, new Promise((_, no) => setTimeout(() => no(new Error('timed out')), ms))]);

  // An AudioContext at exactly `hz`, and the worklet in it. The context is made before anything is awaited, so that
  // a tap still counts. A browser that refuses the rate (it throws, or opens another rate) is an error with `.rate`.
  async function prepare(hz) {
    const AC = window.AudioContext || window.webkitAudioContext;
    try {
      ctx = new AC({ sampleRate: hz, latencyHint: 'interactive' });
      if (ctx.sampleRate !== hz) throw new Error('got ' + ctx.sampleRate);
    } catch (cause) {
      dropContext();
      const err = new Error('this browser will not play ' + hz + ' Hz directly (' + cause.message + ')');
      err.rate = true;
      throw err;
    }
    const mine = ctx;
    const resumed = ctx.resume(); // inside the tap
    try { if (navigator.audioSession) navigator.audioSession.type = 'playback'; } catch { /* older Safari */ }
    const url = URL.createObjectURL(new Blob([WORKLET], { type: 'text/javascript' }));
    try { await ctx.audioWorklet.addModule(url); } finally { URL.revokeObjectURL(url); }
    await within(resumed, 3000); // without a tap the browser never starts it
    if (ctx !== mine) { const err = new Error('stopped'); err.name = 'AbortError'; throw err; }
    node = new AudioWorkletNode(ctx, 'zpkt-listen', {
      numberOfInputs: 0, outputChannelCount: [2], processorOptions: { target: TARGET_MS, max: MAX_MS },
    });
    node.port.onmessage = e => {
      const m = e.data;
      stats.ms = m.ms; stats.under = m.under; stats.drops = m.drops;
      level(m.peak);
    };
    node.connect(ctx.destination);
    stats.mode = 'pcm';
    stats.rate = hz;
    stats.out = Math.round(1000 * ((ctx.baseLatency || 0) + (ctx.outputLatency || 0)));
  }
  async function startPcm() {
    // The status has usually said the rate by now (it is asked when the page loads), so the context made inside the
    // tap is the right one. The stream then says the rate for certain, and connect() changes the context if not.
    await prepare(rate || USUAL_RATE);
    await connect();
  }
  async function connect() {
    abort = new AbortController();
    const mine = abort;
    const res = await fetch(BASE + '/stream.pcm', { signal: mine.signal, cache: 'no-store' });
    if (!res.ok) {
      let text = 'The Mac did not start the sound.';
      try { text = (await res.json()).error || text; } catch { /* not JSON */ }
      const err = new Error(text);
      err.plain = true;
      throw err;
    }
    const hz = await rateOf(res);
    rate = hz;
    if (abort !== mine) return;
    if (!ctx || ctx.sampleRate !== hz) {
      // Another rate than the context was made for (the first guess was wrong, or the capture changed): the sound is
      // never played at a wrong rate. Make the context again at the stream's rate, or give the stream up.
      dropContext();
      try { await prepare(hz); } catch (err) { mine.abort(); if (abort === mine) abort = null; dropContext(); throw err; }
      if (abort !== mine) return;
    }
    set('on');
    pump(res.body.getReader(), mine);
  }
  async function pump(reader, mine) {
    let rest = new Uint8Array(0);
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        stats.bytes += value.length;
        if (stats.bytes > USUAL_RATE) tries = 0; // sound is really arriving
        let buf = value;
        if (rest.length) { buf = new Uint8Array(rest.length + value.length); buf.set(rest); buf.set(value, rest.length); }
        const whole = buf.length - (buf.length % 4);
        rest = buf.slice(whole);
        if (whole && node) {
          const out = buf.slice(0, whole).buffer; // a copy, aligned, that the worklet may keep
          node.port.postMessage(out, [out]);
        }
      }
    } catch { /* aborted, or the network dropped */ }
    if (abort === mine && state === 'on') retry();
  }

  function startMp3() {
    return new Promise((resolve, reject) => {
      audio = new Audio();
      audio.preload = 'none';
      const mine = audio;
      audio.addEventListener('playing', () => { if (audio !== mine) return; stats.mode = 'mp3'; tries = 0; set('on'); level(0.25); resolve(); });
      audio.addEventListener('error', () => { if (audio !== mine) return; if (state === 'on') retry(); else reject(new Error('mp3')); });
      audio.addEventListener('ended', () => { if (audio === mine && state === 'on') retry(); });
      audio.src = BASE + '/stream.mp3?t=' + Date.now();
      audio.play().catch(reject); // inside the tap
    });
  }

  async function start() {
    hideWhy();
    set('connecting');
    try {
      if (canWorklet()) {
        try { return await startPcm(); } catch (err) {
          teardown();
          if (err.plain) throw err;
          if (err.name === 'AbortError') return;
        }
      }
      await startMp3();
    } catch (err) {
      teardown();
      let text = err.plain ? err.message : '';
      if (!text) {
        try { const s = await status(); text = s.available ? '' : s.reason; } catch { text = 'The Mac did not answer. Check the connection and tap again.'; }
      }
      if (!text) { set('off'); throw err; } // most likely the browser wanted a tap
      fail(text);
    }
  }

  btn.addEventListener('click', e => {
    e.stopPropagation();
    armed = false;
    if (state === 'on' || state === 'connecting') return stop(false);
    if (state === 'unavailable' && why) return hideWhy();
    if (state === 'unavailable') {
      // Show the reason at once, and look again: it may have been put right since.
      explain(reason);
      status().then(s => { if (s.available) { hideWhy(); reason = ''; set('off'); } else if (s.reason !== reason) { reason = s.reason; explain(reason); } }).catch(() => {});
      return;
    }
    remember(true);
    tries = 0;
    start().catch(() => {});
  });

  // One-tap resume: listening was on when the last page was left, so the first tap anywhere starts it again.
  let armed = remembered();
  document.addEventListener('click', e => {
    if (!armed || btn.contains(e.target)) return;
    armed = false;
    if (state === 'off' && remembered()) start().catch(() => {});
  }, true);

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && ctx && ctx.state !== 'running') ctx.resume().catch(() => {});
  });
  addEventListener('pagehide', () => { if (state !== 'unavailable') stop(true); });

  set('off');
  status().then(s => {
    if (!s.available && state === 'off') { reason = s.reason; armed = false; set('unavailable'); }
  }).catch(() => { slot.replaceChildren(); }); // no Listen adapter on this server: draw nothing
}

function boot() {
  const slot = document.getElementById('listen');
  if (slot && !slot.querySelector('.lsn')) mount(slot);
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
