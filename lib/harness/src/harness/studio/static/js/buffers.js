// Decoded audio, kept in a small LRU by bytes. Each entry remembers which messages use it, so it can
// be released when they leave the chat window.

export const DECODED_BUDGET_BYTES = 48 * 1024 * 1024;   // float32 PCM: about 4 minutes of stereo at 48 kHz

export class BufferCache {
  #entries = new Map();      // url -> {promise, bytes, owners}; Map order is the LRU order
  #bytes = 0;

  constructor(context, budget = DECODED_BUDGET_BYTES) {
    this.context = context;  // () => AudioContext
    this.budget = budget;
  }

  get bytes() {
    return this.#bytes;
  }

  /** The decoded buffer for `url`, fetched once; `owner` is the seq of the message it belongs to. */
  load(url, owner) {
    let entry = this.#entries.get(url);
    if (entry) {
      this.#entries.delete(url);           // most recently used goes last
      this.#entries.set(url, entry);
    } else {
      entry = { bytes: 0, owners: new Set() };
      entry.promise = this.#decode(url).then(
        (buffer) => {
          entry.bytes = buffer.length * buffer.numberOfChannels * 4;
          if (this.#entries.get(url) === entry) {
            this.#bytes += entry.bytes;
            this.#evict(url);
          }
          return buffer;
        },
        (err) => {
          if (this.#entries.get(url) === entry) this.#entries.delete(url);
          throw err;
        });
      this.#entries.set(url, entry);
    }
    if (owner != null) entry.owners.add(owner);
    return entry.promise;
  }

  /** These messages left the window: forget audio that only they used. */
  release(owners) {
    for (const [url, entry] of [...this.#entries]) {
      for (const seq of owners) entry.owners.delete(seq);
      if (!entry.owners.size) this.#forget(url, entry);
    }
  }

  clear() {
    for (const [url, entry] of [...this.#entries]) this.#forget(url, entry);
  }

  async #decode(url) {
    const res = await fetch(url, { credentials: 'same-origin' });
    if (!res.ok) throw new Error(`${res.status} for ${url}`);
    return this.context().decodeAudioData(await res.arrayBuffer());
  }

  #evict(keep) {
    for (const [url, entry] of this.#entries) {
      if (this.#bytes <= this.budget) break;
      if (url !== keep) this.#forget(url, entry);
    }
  }

  #forget(url, entry) {
    this.#entries.delete(url);
    this.#bytes -= entry.bytes;
  }
}
