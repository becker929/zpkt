// The Bench: a Max/MSP-style patcher of the lab's widgets (js/bench/). Play mounts it in a rack at its bottom:
//
//   import { mountBench } from '../play/bench.js';
//   mountBench(rackBody, ctx);       // returns the Bench (bench.add(type, params), bench.fit(), bench.reset() ...)
//
// Everything it starts (its frame loop, the widgets' listeners, the modulation it puts on params) is registered
// with ctx.own and stops when the surface unmounts. The patch is kept on this phone.

import { Bench } from '../bench/bench.js';

export function mountBench(root, ctx) {
  const bench = new Bench(root, ctx);
  root.bench = bench;                       // for tests and the console
  return bench;
}
