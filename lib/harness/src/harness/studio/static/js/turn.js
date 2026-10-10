// Whose turn it is, seen from this page: the Mac's phase, whether this page owns the mic and the
// speaker, what the big button does now, and whether the mic should be open.
//
// The mic is open exactly when the Mac has asked for it (`listen`, not yet `unlisten`), the user has
// not ended the turn, and nothing is playing: a bubble tapped while listening closes the mic, plays,
// and the mic reopens when it has finished if the Mac is still listening.
import { Emitter } from './emitter.js';

/**
 * What a tap on the turn button does:
 *   start     take the mic and speaker (the first tap also unlocks audio and asks for the mic)
 *   listen    end my turn, same as saying the stop word
 *   work      interrupt Claude
 *   answer    stop Claude's answer: my turn
 *   playback  stop what I tapped
 */
export class Turn extends Emitter {
  connected = false;
  started = false;          // a tap has started this page (audio is unlocked)
  owner = false;            // this page has the mic and the speaker
  phase = 'idle';
  label = '';
  speechReady = true;
  caption = '';
  #listenTurn = null;       // the turn the Mac asked us to listen for
  #endedTurn = null;        // a turn the user ended by tapping

  constructor({ socket, mic, engine, prefs, timing, wake }) {
    super();
    Object.assign(this, { socket, mic, engine, prefs, timing, wake });
    engine.on('busy', () => this.#syncMic());
    engine.on('idle', () => this.#syncMic());
    engine.on('nowplaying', () => this.#changed());
    mic.on('state', () => this.#changed());
  }

  get mode() {
    if (!this.started || !this.owner) return 'start';
    if (this.phase === 'working') return 'work';
    if (this.phase === 'responding') return 'answer';
    if (this.engine.busy) return 'playback';
    if (this.phase === 'listening') return 'listen';
    return 'start';
  }

  get listening() {
    return this.mic.state !== 'closed';
  }

  tap() {
    this.engine.unlock();       // every tap may be the gesture iOS wants (the first start, or after a call)
    switch (this.mode) {
      case 'start':
        this.start();
        break;
      case 'listen':
        this.socket.send({ type: 'end_turn' });
        this.#endedTurn = this.#listenTurn;
        this.#syncMic();
        break;
      case 'work':
      case 'answer':
        this.engine.stop();
        this.socket.send({ type: 'interrupt' });
        break;
      case 'playback':
        this.engine.stop();
        break;
    }
    this.#changed();
  }

  /** Take the mic and the speaker, with hands-free on. */
  start() {
    const first = !this.started;
    this.started = true;
    this.owner = true;
    this.prefs.set('handsfree', true);
    this.wake.set(true);
    this.engine.resetCount();
    this.socket.send({ type: 'start' });
    if (first) this.mic.prime();
    this.#syncMic();
    this.#changed();
  }

  setHandsfree(on) {
    this.prefs.set('handsfree', on);
    this.wake.set(on && this.started);
    if (!on) this.socket.send({ type: 'pause' });
    // Mid-turn, the Mac reads the preference when the answer ends; from idle, it takes a start.
    else if (this.started && this.phase === 'idle') this.start();
    this.#changed();
  }

  // --- from the Mac --------------------------------------------------------------------------------

  connection(state) {
    this.connected = state === 'open';
    if (!this.connected) {
      this.#listenTurn = null;
      this.engine.endStreams();
    }
    this.#syncMic();
    this.#changed();
  }

  welcome(msg) {
    this.owner = !!msg.owner;
    this.speechReady = msg.speech_ready !== false;
    this.#setPhase(msg.phase, msg.turn, msg.label);
    // Back after a dropped connection, and the Mac no longer counts us as the owner: take it back.
    if (this.started && !this.owner && this.prefs.get('handsfree')) this.start();
  }

  phaseChanged(msg) {
    this.#setPhase(msg.phase, msg.turn, msg.label);
  }

  listen(msg) {
    this.owner = true;
    this.#listenTurn = msg.turn ?? 'listen';
    this.caption = '';
    if (msg.turn) this.timing.turn = msg.turn;
    this.#syncMic();
    this.#changed();
  }

  unlisten(msg) {
    if (!msg.turn || msg.turn === this.#listenTurn) this.#listenTurn = null;
    this.#syncMic();
    this.#changed();
  }

  captionChanged(msg) {
    this.caption = msg.text ?? '';
    this.emit('caption', this.caption);
  }

  #setPhase(phase, turn, label) {
    this.phase = phase || 'idle';
    this.label = label ?? '';
    if (turn) this.timing.turn = turn;
    if (this.phase !== 'listening') {
      this.#listenTurn = null;
      this.caption = '';
    }
    this.#syncMic();
    this.#changed();
  }

  #syncMic() {
    const open = this.started && this.connected && this.#listenTurn && this.#listenTurn !== this.#endedTurn
      && !this.engine.busy;
    this.mic.want(open ? this.#listenTurn : null);
  }

  #changed() {
    this.emit('change', this);
  }
}
