// The WebSocket to the Mac (/studio/ws): JSON text frames, and binary frames whose first byte names
// the channel. It says hello on every (re)connect, reconnects with backoff, and pings so a dead
// connection (a car leaving coverage) is noticed and replaced.
import { Emitter } from './emitter.js';

const BACKOFF_MS = [300, 700, 1500, 3000, 6000, 10000];
const PING_EVERY_MS = 15000;
const DEAD_AFTER_MS = 40000;       // nothing heard for this long: the socket is gone, whatever it says
const SPEECH_CHANNEL = 0x02;

export const socketUrl = (base) => `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${base}/ws`;

export class Socket extends Emitter {
  #ws = null;
  #attempt = 0;
  #retry = 0;
  #ping = 0;
  #heard = 0;
  state = 'connecting';            // connecting | open | closed

  /** `hello()` builds the first message of every connection. */
  constructor(url, hello) {
    super();
    this.url = url;
    this.hello = hello;
    addEventListener('online', () => this.#now());
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') this.#now();
    });
  }

  connect() {
    clearTimeout(this.#retry);
    this.#retry = 0;
    if (this.#ws) return;
    this.#setState('connecting');
    const ws = new WebSocket(this.url);
    ws.binaryType = 'arraybuffer';
    this.#ws = ws;
    ws.onopen = () => {
      this.#heard = Date.now();
      this.#setState('open');
      ws.send(JSON.stringify(this.hello()));
      this.#ping = setInterval(() => this.#keepalive(), PING_EVERY_MS);
    };
    ws.onmessage = (e) => {
      this.#heard = Date.now();
      this.#receive(e.data);
    };
    ws.onclose = () => this.#lost(ws);
  }

  get open() {
    return this.#ws?.readyState === WebSocket.OPEN && this.state === 'open';
  }

  /** Send a JSON message; dropped while disconnected (everything that matters is resent with hello). */
  send(msg) {
    if (!this.open) return false;
    this.#ws.send(JSON.stringify(msg));
    return true;
  }

  sendBinary(bytes) {
    if (!this.open) return false;
    this.#ws.send(bytes);
    return true;
  }

  /** The Mac welcomed us: the connection is good, so the next failure starts the backoff afresh. */
  confirm() {
    this.#attempt = 0;
  }

  #receive(data) {
    if (typeof data === 'string') {
      let msg;
      try {
        msg = JSON.parse(data);
      } catch {
        return;
      }
      this.emit('message', msg);
      return;
    }
    const view = new DataView(data);
    if (view.byteLength >= 5 && view.getUint8(0) === SPEECH_CHANNEL) {
      const pcmBytes = (view.byteLength - 5) & ~1;
      this.emit('speech', { stream: view.getUint32(1), pcm: new DataView(data, 5, pcmBytes) });
    }
  }

  #keepalive() {
    if (Date.now() - this.#heard > DEAD_AFTER_MS) {
      const ws = this.#ws;
      ws?.close();
      this.#lost(ws);               // don't wait for a closing handshake that cannot arrive
      return;
    }
    this.send({ type: 'ping', t: Date.now() });
  }

  #lost(ws) {
    if (!ws || this.#ws !== ws) return;
    ws.onopen = ws.onmessage = ws.onclose = null;
    this.#ws = null;
    clearInterval(this.#ping);
    this.#setState('closed');
    const base = BACKOFF_MS[Math.min(this.#attempt, BACKOFF_MS.length - 1)];
    this.#attempt += 1;
    this.#retry = setTimeout(() => this.connect(), base * (0.8 + Math.random() * 0.4));
  }

  /** The network or the page came back: try now rather than at the end of the backoff. */
  #now() {
    if (!this.#ws) this.connect();
  }

  #setState(state) {
    if (this.state === state) return;
    this.state = state;
    this.emit('state', state);
  }
}
