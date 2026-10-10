// The dock: one big turn button whose meaning follows the phase, the live caption while listening,
// and a keyboard for typing a turn instead.
import { setText } from './dom.js';
import { icon } from './icons.js';

const BUTTON = {
  start: { icon: 'mic', label: 'Start', hint: 'Tap, then talk' },
  talk: { icon: 'mic', label: 'Talk', hint: 'Tap to talk' },
  listen: { icon: 'send', label: 'Send', hint: 'Tap or say “tomato” to send' },
  work: { icon: 'stop', label: 'Interrupt', hint: 'Claude is working · tap to interrupt' },
  answer: { icon: 'mic', label: 'Talk', hint: 'Tap to cut in' },
  playback: { icon: 'stop', label: 'Stop', hint: 'Tap to stop' },
  offline: { icon: 'mic', label: 'Start', hint: 'Reconnecting…' },
};

export class Dock {
  #face = '';

  constructor(dom, { turn, socket }) {
    Object.assign(this, { dom, turn, socket });
    dom.turn.addEventListener('click', () => turn.tap());
    dom.keyboard.addEventListener('click', () => this.#toggleComposer());
    dom.composer.addEventListener('submit', (e) => {
      e.preventDefault();
      this.#send();
    });
    dom.input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') this.#toggleComposer(false);
    });
    turn.on('caption', () => this.#caption());
  }

  render() {
    const { dom, turn } = this;
    let mode = turn.mode;
    if (mode === 'start' && turn.started) mode = 'talk';
    if (this.socket.state !== 'open' && mode === 'start') mode = 'offline';
    const look = BUTTON[mode];
    dom.turn.dataset.mode = mode;
    dom.turn.setAttribute('aria-label', look.label);
    dom.turn.classList.toggle('is-live', turn.listening);
    if (this.#face !== look.icon) {
      this.#face = look.icon;
      dom.face.replaceChildren(icon(look.icon));
    }
    setText(dom.hint, look.hint);
    this.#caption();
  }

  /** What the Mac has heard so far, while listening: the end of it, where the new words are. */
  #caption() {
    const { dom, turn } = this;
    const text = turn.phase === 'listening' && dom.composer.hidden ? turn.caption : '';
    setText(dom.caption, text.length > 140 ? `…${text.slice(-140)}` : text);
    dom.caption.classList.toggle('is-empty', !text);
  }

  #toggleComposer(open = this.dom.composer.hidden) {
    const { dom } = this;
    dom.composer.hidden = !open;
    dom.keyboard.setAttribute('aria-expanded', String(open));
    dom.keyboard.classList.toggle('is-on', open);
    if (open) dom.input.focus();
    else dom.input.blur();
    this.#caption();
  }

  #send() {
    const text = this.dom.input.value.trim();
    if (!text || !this.socket.send({ type: 'say', text })) return;
    this.dom.input.value = '';
    this.#toggleComposer(false);
  }
}
