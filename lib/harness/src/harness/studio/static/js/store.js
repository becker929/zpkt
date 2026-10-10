// The window of messages the page holds: at most WINDOW_CAP, ordered by seq.
//
// Live messages are appended while the window holds the newest ones; the oldest is dropped to make
// room. Loading earlier pages shifts the window back in time, dropping from the newest end: the
// window is then "detached" and live messages are not added (the view offers "Jump to latest",
// which replaces the window with the newest page).
//
// Every change is emitted as {added, updated, removed, reset} so the view can patch the DOM in place
// and the audio engine can release what belonged to removed messages.
import { Emitter } from './emitter.js';

export const WINDOW_CAP = 60;
export const PAGE_SIZE = 30;

export class MessageWindow extends Emitter {
  #bySeq = new Map();
  seqs = [];                 // ascending
  hasMoreBefore = false;     // older messages exist on the Mac
  detached = false;          // newer messages exist on the Mac that are not in the window

  /** The view's say on dropping the oldest message: not while someone is reading it. */
  canDrop = () => true;

  get size() {
    return this.seqs.length;
  }

  get(seq) {
    return this.#bySeq.get(seq);
  }

  get first() {
    return this.#bySeq.get(this.seqs[0]);
  }

  /** The newest page (welcome, Jump to latest, or a new conversation): replaces everything. */
  replace(items, hasMore) {
    const removed = [...this.seqs];
    const kept = [...items].sort((a, b) => a.seq - b.seq).slice(-WINDOW_CAP);
    this.#bySeq = new Map(kept.map((m) => [m.seq, m]));
    this.seqs = kept.map((m) => m.seq);
    this.hasMoreBefore = hasMore || kept.length < items.length;
    this.detached = false;
    this.emit('change', { reset: true, added: [...this.seqs], removed: removed.filter((s) => !this.#bySeq.has(s)) });
  }

  /** A live message, new or changed. */
  upsert(msg) {
    const old = this.#bySeq.get(msg.seq);
    if (old) {
      if ((msg.rev ?? 0) < (old.rev ?? 0)) return;
      this.#bySeq.set(msg.seq, msg);
      this.emit('change', { updated: [msg.seq] });
      return;
    }
    if (this.detached) return;                                          // fetched fresh on Jump to latest
    if (this.seqs.length && msg.seq < this.seqs[0] && this.hasMoreBefore) return;   // older than the window
    const removed = [];
    if (this.seqs.length >= WINDOW_CAP) {
      const oldest = this.seqs[0];
      if (!this.canDrop(oldest)) {
        this.detached = true;
        this.emit('change', { detached: true });
        return;
      }
      this.#drop(oldest);
      removed.push(oldest);
      this.hasMoreBefore = true;
    }
    this.#bySeq.set(msg.seq, msg);
    this.seqs.splice(insertionPoint(this.seqs, msg.seq), 0, msg.seq);
    this.emit('change', { added: [msg.seq], removed });
  }

  /** An earlier page (oldest first), from Load earlier. */
  prepend(items, hasMore) {
    const fresh = items.filter((m) => !this.#bySeq.has(m.seq) && (!this.seqs.length || m.seq < this.seqs[0]));
    for (const m of fresh) this.#bySeq.set(m.seq, m);
    this.seqs = [...fresh.map((m) => m.seq).sort((a, b) => a - b), ...this.seqs];
    this.hasMoreBefore = hasMore;
    const removed = [];
    while (this.seqs.length > WINDOW_CAP) {
      const newest = this.seqs[this.seqs.length - 1];
      this.#drop(newest);
      removed.push(newest);
      this.detached = true;
    }
    this.emit('change', { added: fresh.map((m) => m.seq), removed });
  }

  #drop(seq) {
    this.#bySeq.delete(seq);
    const i = this.seqs.indexOf(seq);
    if (i >= 0) this.seqs.splice(i, 1);
  }
}

/** Where `seq` goes in the ascending array (binary search). */
export function insertionPoint(seqs, seq) {
  let lo = 0;
  let hi = seqs.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (seqs[mid] < seq) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}
