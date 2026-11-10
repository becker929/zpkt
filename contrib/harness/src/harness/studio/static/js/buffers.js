// Decoded audio, kept in a small LRU by bytes. Each entry remembers which messages use it, so it can
// be released when they leave the chat window.

export const DECODED_BUDGET_BYTES = 64 * 1024 * 1024;   // float32 PCM: about 5.8 minutes of stereo at 48 kHz

export class BufferCache {
  #entries = new Map();      // url -> {promise, bytes, owners}; Map order is the LRU order
  #raw = new Map();          // url -> {promise (the file's bytes), owners}: fetched before a context could decode it
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
      entry = { bytes: 0, owners: new Set(this.#raw.get(url)?.owners) };
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

  /** Have `url` in memory soon: decoded if there is a context, else fetched now and decoded once there is one
   * (decodeAhead). Resolves when it is decoded or fetched. */
  preload(url, owner) {
    if (this.#entries.has(url) || this.context()) return this.load(url, owner).then(() => undefined);
    let raw = this.#raw.get(url);
    if (!raw) {
      raw = { owners: new Set(), promise: fetchBytes(url) };
      raw.promise.catch(() => {
        if (this.#raw.get(url) === raw) this.#raw.delete(url);
      });
      this.#raw.set(url, raw);
    }
    if (owner != null) raw.owners.add(owner);
    return raw.promise.then(() => undefined);
  }

  /** There is a context now: decode what was fetched ahead. */
  decodeAhead() {
    for (const url of [...this.#raw.keys()]) this.load(url).catch(() => {});
  }

  /** These messages left the window: forget audio that only they used. */
  release(owners) {
    for (const [url, entry] of [...this.#entries]) {
      for (const seq of owners) entry.owners.delete(seq);
      if (!entry.owners.size) this.#forget(url, entry);
    }
    for (const [url, raw] of [...this.#raw]) {
      for (const seq of owners) raw.owners.delete(seq);
      if (!raw.owners.size) this.#raw.delete(url);
    }
  }

  clear() {
    for (const [url, entry] of [...this.#entries]) this.#forget(url, entry);
    this.#raw.clear();
  }

  async #decode(url) {
    const raw = this.#raw.get(url);
    this.#raw.delete(url);
    const bytes = raw ? await raw.promise : await fetchBytes(url);
    return this.context().decodeAudioData(bytes);
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

async function fetchBytes(url) {
  const res = await fetch(url, { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status} for ${url}`);
  return res.arrayBuffer();
}
