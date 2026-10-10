// The chat list: one element per message, keyed by seq, patched in place.
//
// Store changes are collected and written once per animation frame. Consecutive activity rows live
// in one "steps" group. The view keeps the reader's place itself (CSS scroll anchoring is off: Safari
// has none, and two schemes would fight): a reader at the bottom stays at the bottom; otherwise the
// first message they see stays where it is, whatever is added, dropped or resized above it.
import { Emitter } from './emitter.js';
import {
  createBubble, createSteps, isActivity, refreshSteps, setPlayhead, setPlaying, stepsList, updateBubble,
} from './bubbles.js';

const AT_BOTTOM_PX = 64;      // this close to the bottom counts as reading the newest message

export class ChatView extends Emitter {
  #els = new Map();            // seq -> element (a bubble, or an activity row inside a steps group)
  #added = new Set();
  #updated = new Set();
  #removed = new Set();
  #reset = false;
  #frame = 0;
  #dirtyGroups = new Set();
  #following = true;
  #scrolledTo = 0;             // the scroll position #following was last worked out from
  #anchor = [];                // the first blocks the reader sees, and where they are on screen
  #unseen = 0;
  #resizes;
  #playing = null;
  #ready = false;

  constructor(dom, store) {
    super();
    this.dom = dom;
    this.store = store;
    store.on('change', (change) => this.#collect(change));
    store.canDrop = (seq) => this.#canDrop(seq);
    this.#resizes = new ResizeObserver(() => this.#onResize());
    dom.list.addEventListener('click', (e) => this.#onClick(e));
    dom.scroller.addEventListener('scroll', () => this.#onScroll(), { passive: true });
    dom.loadEarlier.addEventListener('click', () => this.emit('load-earlier'));
    dom.jump.addEventListener('click', () => this.emit('jump'));
  }

  /** The first page has arrived: from now on an empty window means an empty conversation. */
  set ready(value) {
    this.#ready = value;
    this.#schedule();
  }

  element(seq) {
    return this.#els.get(seq);
  }

  get messageCount() {
    return this.#els.size;
  }

  setLoading(on) {
    const button = this.dom.loadEarlier;
    button.disabled = on;
    button.classList.toggle('is-loading', on);
    button.setAttribute('aria-busy', String(on));
  }

  /** Show which shots are visible: a level hides every shot above it. */
  setShotLevel(level) {
    this.dom.list.dataset.shots = level;
  }

  setNowPlaying(seq) {
    if (this.#playing === seq) return;
    const old = this.#els.get(this.#playing);
    if (old) {
      setPlaying(old, false);
      setPlayhead(old, 0, null);
    }
    this.#playing = seq;
    const el = this.#els.get(seq);
    if (el) setPlaying(el, true);
  }

  updatePlayhead(seq, fraction, side) {
    const el = this.#els.get(seq);
    if (el) setPlayhead(el, fraction, side);
  }

  /** Scroll to the newest message and keep following it. */
  scrollToLatest({ smooth = false } = {}) {
    this.#following = true;
    this.#unseen = 0;
    const { scroller } = this.dom;
    scroller.scrollTo({ top: scroller.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
    this.#scrolledTo = scroller.scrollTop;
    this.#anchor = [];
    this.#syncJump();
  }

  // --- collecting changes -----------------------------------------------------------------------

  #collect({ added = [], updated = [], removed = [], reset = false }) {
    if (reset) this.#reset = true;
    for (const seq of removed) {
      if (this.#added.delete(seq)) continue;
      this.#updated.delete(seq);
      this.#removed.add(seq);
    }
    for (const seq of added) {
      if (this.#removed.delete(seq)) this.#updated.add(seq);
      else this.#added.add(seq);
    }
    for (const seq of updated) if (!this.#added.has(seq)) this.#updated.add(seq);
    this.#schedule();
  }

  #schedule() {
    if (!this.#frame) this.#frame = requestAnimationFrame(() => this.#flush());
  }

  // --- writing the DOM, once per frame -----------------------------------------------------------

  #flush() {
    this.#frame = 0;
    this.#catchUpScroll();
    const newestBefore = this.#newestRendered();

    if (this.#reset) this.#reconcile();
    else this.#apply();
    this.#reset = false;
    this.#added.clear();
    this.#updated.clear();
    this.#removed.clear();
    for (const group of this.#dirtyGroups) if (group.isConnected) refreshSteps(group, this.#rowsOf(group));
    this.#dirtyGroups.clear();
    this.#syncEdges();
    this.#keepPlace();
    if (!this.#following) this.#unseen += this.store.seqs.filter((seq) => seq > newestBefore).length;
    this.#syncJump();
  }

  #apply() {
    for (const seq of this.#removed) this.#remove(seq);
    const added = [...this.#added].sort((a, b) => a - b);
    // A page from the past is built from its newest message down, so each one lands on what is below it
    // (and a run of steps at the old top grows at its front rather than being split).
    if (added.length && added[added.length - 1] < this.#oldestRendered()) added.reverse();
    for (const seq of added) {
      const msg = this.store.get(seq);
      if (msg && !this.#els.has(seq)) this.#insert(msg);
    }
    for (const seq of this.#updated) {
      const msg = this.store.get(seq);
      const el = this.#els.get(seq);
      if (msg && el) this.#update(el, msg);
    }
  }

  /** After a reset (welcome, Jump to latest, new conversation): keep what is still there, patch, add the rest. */
  #reconcile() {
    const keep = new Set(this.store.seqs);
    for (const seq of [...this.#els.keys()]) if (!keep.has(seq)) this.#remove(seq);
    for (const seq of this.store.seqs) {
      const msg = this.store.get(seq);
      const el = this.#els.get(seq);
      if (!el) this.#insert(msg);
      else if (el.dataset.rev !== String(msg.rev ?? 0) || el.dataset.kind !== msg.kind) this.#update(el, msg);
    }
  }

  #insert(msg) {
    const seqs = this.store.seqs;
    const i = seqs.indexOf(msg.seq);
    const el = createBubble(msg);
    el.dataset.kind = msg.kind;
    this.#els.set(msg.seq, el);
    // A row joins a run of steps only through the messages right next to it, so a run never spans a gap
    // that is still being filled.
    const before = this.#els.get(seqs[i - 1]) ?? null;
    const after = this.#els.get(seqs[i + 1]) ?? null;
    if (isActivity(msg)) this.#insertRow(el, before, after, i);
    else this.#insertBlock(el, before, after, i);
    if (this.#playing === msg.seq) setPlaying(el, true);
  }

  #update(el, msg) {
    if (el.dataset.kind !== msg.kind) {      // never expected; rebuild rather than patch the wrong shape
      this.#remove(msg.seq);
      this.#insert(msg);
      return;
    }
    updateBubble(el, msg);
    if (isActivity(msg)) this.#dirtyGroups.add(groupOf(el));
  }

  #insertRow(row, before, after, i) {
    if (isRow(before)) {
      before.after(row);
      if (isRow(after) && groupOf(after) !== groupOf(row)) this.#merge(groupOf(row), groupOf(after));
    } else if (isRow(after)) {
      after.before(row);
    } else {
      const group = createSteps();
      stepsList(group).append(row);
      this.#place(group, i);
    }
    this.#dirtyGroups.add(groupOf(row));
  }

  #insertBlock(el, before, after, i) {
    if (isRow(before) && isRow(after) && groupOf(before) === groupOf(after)) {
      // It lands inside a run of steps: split the run around it.
      const group = groupOf(before);
      const tail = createSteps();
      const list = stepsList(tail);
      for (let row = after; row; ) {
        const next = row.nextElementSibling;
        list.append(row);
        row = next;
      }
      group.after(el);
      el.after(tail);
      this.#observe(el);
      this.#observe(tail);
      this.#dirtyGroups.add(group).add(tail);
      return;
    }
    this.#place(el, i);
  }

  /** Put a block where the message at index i belongs: after the nearest one shown before it. */
  #place(block, i) {
    const seqs = this.store.seqs;
    const prev = this.#nearest(seqs, i, -1);
    const next = prev ? null : this.#nearest(seqs, i, +1);
    if (prev) blockOf(prev).after(block);
    else if (next) blockOf(next).before(block);
    else this.dom.list.append(block);
    this.#observe(block);
  }

  /** The nearest message shown before (dir -1) or after (+1) index i, by seq order. */
  #nearest(seqs, i, dir) {
    for (let j = i + dir; j >= 0 && j < seqs.length; j += dir) {
      const el = this.#els.get(seqs[j]);
      if (el) return el;
    }
    return null;
  }

  /** Two runs of steps that now touch become one: the first takes the second's rows. */
  #merge(first, second) {
    stepsList(first).append(...stepsList(second).children);
    this.#drop(second);
    this.#dirtyGroups.add(first);
  }

  #remove(seq) {
    const el = this.#els.get(seq);
    if (!el) return;
    this.#els.delete(seq);
    if (isRow(el)) {
      const group = groupOf(el);
      el.remove();
      if (stepsList(group).firstElementChild) this.#dirtyGroups.add(group);
      else this.#drop(group);
      return;
    }
    const before = el.previousElementSibling;
    const after = el.nextElementSibling;
    this.#drop(el);
    if (isGroup(before) && isGroup(after)) this.#merge(before, after);
  }

  #drop(block) {
    this.#resizes.unobserve(block);
    this.#dirtyGroups.delete(block);
    block.remove();
  }

  #observe(block) {
    this.#resizes.observe(block);
  }

  #rowsOf(group) {
    return [...stepsList(group).children].map((row) => this.store.get(Number(row.dataset.seq))).filter(Boolean);
  }

  #oldestRendered() {
    let oldest = Infinity;
    for (const seq of this.#els.keys()) oldest = Math.min(oldest, seq);
    return oldest;
  }

  #newestRendered() {
    let newest = -Infinity;
    for (const seq of this.#els.keys()) newest = Math.max(newest, seq);
    return newest;
  }

  #syncEdges() {
    const { loadEarlier, startOf, empty } = this.dom;
    const n = this.store.size;
    loadEarlier.hidden = !this.store.hasMoreBefore;
    startOf.hidden = this.store.hasMoreBefore || n === 0;
    empty.hidden = n > 0 || !this.#ready;
  }

  // --- keeping the reader's place ------------------------------------------------------------------

  /** Remember the first few blocks the reader sees, and where they are on screen. */
  #capture() {
    const top = this.dom.scroller.getBoundingClientRect().top;
    this.#anchor = [];
    for (const block of this.dom.list.children) {
      const r = block.getBoundingClientRect();
      if (r.height > 0 && r.bottom > top) {
        this.#anchor.push({ block, top: r.top });
        if (this.#anchor.length === 3) break;
      }
    }
  }

  /** At the bottom: stay there. Otherwise put the first remembered block that is still here back in its place. */
  #keepPlace() {
    const { scroller } = this.dom;
    if (this.#following) {
      scroller.scrollTop = scroller.scrollHeight;
    } else {
      // The anchor stays the reader's until they scroll: re-taking it here could pick a block just added
      // above, still at its estimated size, and the reader's message would move when that one is drawn.
      this.#anchor = this.#anchor.filter((a) => a.block.isConnected);
      const anchor = this.#anchor[0];
      const moved = anchor ? anchor.block.getBoundingClientRect().top - anchor.top : 0;
      if (moved) scroller.scrollTop += moved;
      if (!anchor) this.#capture();
    }
    this.#scrolledTo = scroller.scrollTop;
  }

  /** Something changed height (a new block drawn for the first time, an image, a caption unfolding). */
  #onResize() {
    this.#catchUpScroll();
    this.#keepPlace();
  }

  #onScroll() {
    const { scrollTop, scrollHeight, clientHeight } = this.dom.scroller;
    if (scrollTop === this.#scrolledTo) return;          // the view's own adjustment, not the reader
    this.#scrolledTo = scrollTop;
    this.#following = scrollHeight - scrollTop - clientHeight <= AT_BOTTOM_PX;
    if (this.#following) {
      this.#unseen = 0;
      this.#anchor = [];
    } else {
      this.#capture();
    }
    this.#syncJump();
  }

  /** The reader scrolled and its scroll event has not arrived yet: take the new position into account now. */
  #catchUpScroll() {
    if (this.dom.scroller.scrollTop !== this.#scrolledTo) this.#onScroll();
  }

  /** The oldest message may go unless the reader is looking at it (or near it). */
  #canDrop(seq) {
    this.#catchUpScroll();
    if (this.#following) return true;
    const el = this.#els.get(seq);
    if (!el) return true;
    const { scroller } = this.dom;
    return blockOf(el).getBoundingClientRect().bottom < scroller.getBoundingClientRect().top - scroller.clientHeight;
  }

  #syncJump() {
    const { jump, jumpCount } = this.dom;
    const show = this.store.detached || (!this.#following && this.#unseen > 0);
    jump.hidden = !show;
    jumpCount.textContent = this.#unseen > 0 ? String(Math.min(this.#unseen, 99)) : '';
    jumpCount.hidden = !(this.#unseen > 0);
  }

  // --- the bubbles' controls -----------------------------------------------------------------------

  #onClick(e) {
    const summary = e.target.closest('summary');
    if (summary && summary.closest('.act') && !summary.closest('.act').classList.contains('has-detail')) {
      e.preventDefault();          // a step with nothing to unfold
      return;
    }
    const control = e.target.closest('[data-action]');
    if (!control || control.disabled) return;
    const holder = control.closest('[data-seq]');
    if (!holder) return;
    this.emit('action', { action: control.dataset.action, seq: Number(holder.dataset.seq), el: holder, control });
  }
}

const isRow = (el) => el?.classList.contains('act');
const isGroup = (el) => el?.classList.contains('steps');
const groupOf = (row) => row.closest('li.steps');
const blockOf = (el) => (isRow(el) ? groupOf(el) : el);
