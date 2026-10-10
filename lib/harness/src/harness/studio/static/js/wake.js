// Keep the screen on while a conversation is running. The browser drops the lock whenever the page is
// hidden, so it is taken again each time the page comes back.

export class ScreenWake {
  #wanted = false;
  #lock = null;
  #pending = false;

  constructor() {
    document.addEventListener('visibilitychange', () => this.#sync());
  }

  set(on) {
    this.#wanted = on;
    this.#sync();
  }

  async #sync() {
    if (!('wakeLock' in navigator) || this.#pending) return;
    if (this.#wanted && !this.#lock && document.visibilityState === 'visible') {
      this.#pending = true;
      try {
        const lock = await navigator.wakeLock.request('screen');
        lock.addEventListener('release', () => {
          if (this.#lock === lock) this.#lock = null;
        });
        this.#lock = lock;
      } catch {
        // Low battery or a browser policy said no: the screen may sleep.
      } finally {
        this.#pending = false;
      }
      if (!this.#wanted) this.#sync();
    } else if (!this.#wanted && this.#lock) {
      const lock = this.#lock;
      this.#lock = null;
      lock.release().catch(() => {});
    }
  }
}
