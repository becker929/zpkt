// The top bar: the connection dot, the phase pill (glanceable: one word and a colour), and the quick
// toggles for autoplay and the screenshot level.
import { setText } from './dom.js';

const SHOT_LABELS = { none: 'None', major: 'Major', minor: 'Minor', firehose: 'Firehose' };
const CONNECTION = { open: 'Connected', connecting: 'Connecting', closed: 'Offline' };

export class TopBar {
  constructor(dom, { turn, engine, prefs, socket }) {
    Object.assign(this, { dom, turn, engine, prefs, socket });
    dom.autoplay.addEventListener('click', () => prefs.set('autoplay', !prefs.get('autoplay')));
    dom.shots.addEventListener('change', () => prefs.set('shots', dom.shots.value));
  }

  render() {
    const { dom, prefs, socket } = this;
    dom.conn.dataset.state = socket.state;
    dom.conn.setAttribute('aria-label', CONNECTION[socket.state]);

    const pill = this.#pill();
    dom.phase.dataset.phase = pill.state;
    setText(dom.phaseText, pill.text);
    setText(dom.phaseDetail, pill.detail ?? '');
    dom.phaseDetail.hidden = !pill.detail;

    dom.autoplay.setAttribute('aria-checked', String(prefs.get('autoplay')));
    dom.shots.value = prefs.get('shots');
    setText(dom.shotsValue, SHOT_LABELS[prefs.get('shots')]);
  }

  /** The A/B side lit while an A/B plays (null: none). */
  setSide(side) {
    if (side) this.dom.phase.dataset.side = side;
    else delete this.dom.phase.dataset.side;
  }

  #pill() {
    const { turn, engine, socket } = this;
    if (socket.state !== 'open') return { state: 'offline', text: CONNECTION[socket.state] };
    const playing = engine.nowPlaying;
    if (playing?.kind === 'music') return { state: 'playing', text: 'Playing' };
    if (playing) return { state: 'speaking', text: 'Speaking' };
    switch (turn.phase) {
      case 'listening':
        return { state: 'listening', text: 'Listening' };
      case 'working':
        return { state: 'working', text: 'Working', detail: turn.label && turn.label !== 'Working' ? turn.label : '' };
      case 'responding':
        return { state: 'speaking', text: 'Speaking' };
      default:
        return turn.label ? { state: 'waiting', text: turn.label } : { state: 'paused', text: 'Paused' };
    }
  }
}
