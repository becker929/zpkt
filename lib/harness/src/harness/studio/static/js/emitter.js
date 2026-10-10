// A minimal event emitter. on() returns the function that unsubscribes.
export class Emitter {
  #handlers = new Map();

  on(type, fn) {
    let set = this.#handlers.get(type);
    if (!set) this.#handlers.set(type, (set = new Set()));
    set.add(fn);
    return () => set.delete(fn);
  }

  emit(type, detail) {
    for (const fn of this.#handlers.get(type) ?? []) fn(detail);
  }
}
