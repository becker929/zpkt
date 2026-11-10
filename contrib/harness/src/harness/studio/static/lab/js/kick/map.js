// The scoop on the loop's bars: which bars of the set's kick stem are scooped (found in its audio: no sub), where the
// loop is now, and the 4 bars a latch covers. The set's own scoop (on, automated over the opening) is a toggle here:
// on, the synth scoops the same bars the stem has scooped; the stem keeps its scoop either way (it is in its audio).

import { h } from '../ui.js';
import { toggle } from '../widgets/fader.js';
import { C, MONO, canvas, panel, rgba } from './util.js';

export function scoopMap(ctx, rig, painter) {
  const { engine } = ctx;
  const cv = canvas('kx-map-cv');
  const read = h('span', { class: 'kx-env-read' });
  painter.add(cv, () => {
    const { g, k, w: W, h: H } = cv.fit();
    g.scale(k, k);
    g.clearRect(0, 0, W, H);
    const seq = engine.stems.sequence;
    const n = seq.length || 24;
    const bw = W / n;
    const pos = engine.position();
    for (let i = 0; i < n; i++) {
      const src = seq[i]?.kick ?? i;
      const scooped = rig.scooped.has(src);
      const silent = src < 0;
      g.fillStyle = silent ? '#0b0b0c' : scooped ? rgba(C.hazard, 0.85) : '#24272c';
      g.fillRect(i * bw + 1, 14, bw - 2, H - 30);
      if (!silent && !scooped) {
        g.fillStyle = 'rgba(255,255,255,0.06)';
        for (let b = 0; b < 4; b++) g.fillRect(i * bw + 2 + (b * (bw - 4)) / 4, H - 22, (bw - 4) / 4 - 1, 4);
      }
      if (scooped) { g.fillStyle = '#120400'; g.font = `700 8px ${MONO}`; g.textAlign = 'center'; g.fillText('S', i * bw + bw / 2, 14 + (H - 30) / 2 + 3); }
      if (i % 4 === 0) { g.fillStyle = C.text3; g.font = `600 8.5px ${MONO}`; g.textAlign = 'left'; g.fillText(String(i + 1), i * bw + 2, 10); }
    }
    // the latch's 4 bars
    const L = rig.scoop.latch;
    if (L && pos.playing) {
      const b0 = L.bar % n;
      g.strokeStyle = C.hazard; g.lineWidth = 2; g.setLineDash([3, 2]);
      g.strokeRect(b0 * bw + 1, 12, Math.min(4, n - b0) * bw - 2, H - 26); g.setLineDash([]);
    }
    if (pos.playing) {
      const x = ((pos.bar % n) + pos.phase) * bw;
      g.fillStyle = C.text; g.fillRect(x, 10, 1.5, H - 22);
    }
    g.fillStyle = C.text3; g.font = `600 8.5px ${MONO}`; g.textAlign = 'left';
    g.fillText(rig.scooped.size ? `SCOOPED IN THE SET: ${rig.scooped.size} BARS` : 'FINDING THE SCOOPED BARS...', 0, H - 3);
  }, { always: true });
  const render = () => {
    const bars = [...rig.scooped].sort((a, b) => a - b).map((b) => b + 1);
    read.textContent = bars.length ? `bars ${bars.join(', ')} of the stem` : '';
  };
  ctx.own(rig.on((type) => { if (type === 'scooped') render(); }));
  render();
  return panel('Scoop map', { sub: 'the loop\'s 24 bars', cls: 'kx-map' },
    h('div', { class: 'kx-env-head' }, h('b', { text: 'STEM' }), read),
    cv,
    h('div', { class: 'kx-layer-row' }, toggle(ctx, 'kick.scoop', { label: 'The set\'s opening scoop', wide: true })),
    h('p', { class: 'rack-note', text: '"Final arrangement starts with the scooped kick." The Short opens on a 48 dB/oct low cut at 126 Hz; scoops also mark structure (bars 43-45 and 121-123 of the song). Latch a scoop from the pad above to hear it anywhere.' }));
}
