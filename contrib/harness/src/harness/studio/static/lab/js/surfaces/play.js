// Play (∞): the lab's strange machines. Demoscene shader instruments, 3D doohickeys and modulators that reach across
// every stage's knobs. Machines that write a knob do it as one undo step per touch; machines that move knobs by
// themselves (power switch on: "Mod", cold blue) add a modulation offset on top of the knob, which goes away when
// they stop, when "Stop all" is pressed, or when this tab closes. Each machine's chips choose what it drives.
// The machines live in ../play/; the Bench (a patcher of the lab's widgets) is the last rack.

import { h, haptic, toast } from '../ui.js';
import { rack, stageHead } from './racks.js';
import { createRoom } from '../play/room.js';
import { furnace } from '../play/furnace.js';
import { tunnel } from '../play/tunnel.js';
import { cube } from '../play/cube.js';
import { crystal } from '../play/crystal.js';
import { tilt } from '../play/tilt.js';
import { balls } from '../play/balls.js';
import { attractor } from '../play/attractor.js';
import { looper } from '../play/looper.js';
import { gyro } from '../play/gyro.js';
import { steps } from '../play/steps.js';
import { flip } from '../play/flip.js';
import { mountBench } from '../play/bench.js';

const MACHINES = [
  ['furnace', 'Furnace', furnace], ['tunnel', 'Tunnel', tunnel], ['cube', 'Cube', cube], ['crystal', 'Crystal', crystal],
  ['tilt', 'Tilt', tilt], ['balls', 'Kick box', balls], ['lorenz', 'Lorenz', attractor], ['loop', 'Loop', looper],
  ['gyro', 'Gyro', gyro], ['steps', 'Steps', steps], ['flip', 'Flip', flip],
];

export default {
  id: 'play',
  title: 'Play',
  n: '∞',
  icon: '<path d="M12 2.5l8.5 4.8v9.4L12 21.5l-8.5-4.8V7.3z"/><path d="M12 12l8.5-4.7M12 12v9.5M12 12L3.5 7.3"/>',
  mount(root, ctx) {
    const room = createRoom(ctx, root);
    ctx.own(() => room.destroy());
    if (window.lab) window.lab.play = room;

    const head = stageHead('Play', 'strange machines',
      'Shader instruments, 3D doohickeys and modulators on HW002\'s knobs. Blue is a machine moving knobs by itself; it lets go when it stops.');
    const jump = h('nav', { class: 'pl-jump', 'aria-label': 'Machines' });
    root.append(head, jump);

    for (const [key, label, make] of MACHINES) {
      let m;
      try { m = make(room); } catch (err) {
        console.error(`play/${key}`, err);
        root.append(rack(label, { note: `This machine broke: ${err.message}` }));
        continue;
      }
      root.append(m.el);
      jump.append(h('button', {
        type: 'button', class: 'pl-jump-b', text: label,
        onclick: () => { haptic(); m.el.scrollIntoView({ behavior: 'smooth', block: 'start' }); },
      }));
    }

    const bench = h('div', { class: 'pl-bench' });
    const benchRack = rack('Bench', { sub: 'a patcher of the lab\'s widgets', cls: 'pl-bench-rack' }, bench);
    benchRack.id = 'pl-bench';
    root.append(benchRack);
    jump.append(h('button', { type: 'button', class: 'pl-jump-b', text: 'Bench', onclick: () => benchRack.scrollIntoView({ behavior: 'smooth', block: 'start' }) }));
    try { mountBench(bench, ctx); } catch (err) {
      console.error('play/bench', err);
      bench.append(h('p', { class: 'rack-note', text: `The bench broke: ${err.message}` }));
    }

    // The dock: which machines are moving knobs now, and one button to stop them all.
    const count = h('span', { class: 'pl-dock-t' });
    const dock = h('div', { class: 'pl-dock', hidden: true },
      h('i', { class: 'pl-led is-on' }), count,
      h('button', {
        type: 'button', class: 'pl-btn', text: 'Keep', 'aria-label': 'Keep what you hear: write it into the knobs',
        onclick: () => {
          const ids = new Set(room.machines.flatMap((m) => (m.running?.() ? m.output?.ids() ?? [] : [])));
          const live = [...ids].map((id) => [id, ctx.store.live(id)]);
          for (const m of room.machines) m.setOn?.(false);
          ctx.store.begin();
          for (const [id, v] of live) ctx.store.set(id, v, { source: 'keep' });
          ctx.store.end();
          haptic(true);
          toast(live.length === 1 ? 'Kept: 1 knob now holds what you heard' : `Kept: ${live.length} knobs now hold what you heard`);
        },
      }),
      h('button', {
        type: 'button', class: 'pl-btn is-alarm', text: 'Stop all',
        onclick: () => {
          for (const m of room.machines) m.setOn?.(false);
          bench.bench?.stop?.();                                    // the Bench's modulators too
          haptic(true);
          toast('Every machine off: the knobs are where they were');
        },
      }));
    root.append(dock);
    const renderDock = () => {
      const on = room.machines.filter((m) => m.running?.()).map((m) => m.title);
      if (bench.bench?.running) on.push('Bench');
      dock.hidden = !on.length;
      count.textContent = on.length ? `Mod: ${on.join(', ')}` : '';
    };
    room.own(room.onChange(renderDock));
    if (bench.bench?.onRun) room.own(bench.bench.onRun(renderDock));
    renderDock();
  },
};
