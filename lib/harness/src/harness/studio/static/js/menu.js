// The menu sheet: hands-free, a new conversation, the last turns' timings, and a way to /skrng.
import { fmtMs, h, setText } from './dom.js';
import { timings as fetchTimings } from './api.js';

const CONFIRM_MS = 4000;      // a second tap within this long confirms "New conversation"
const TURNS_SHOWN = 6;

export class Menu {
  #confirmUntil = 0;

  constructor(dom, { turn, prefs, onNewConversation }) {
    Object.assign(this, { dom, turn, prefs, onNewConversation });
    dom.open.addEventListener('click', () => this.open());
    dom.sheet.addEventListener('click', (e) => {
      if (e.target === dom.sheet || e.target.closest('[data-close]')) this.close();    // the backdrop, or Close
    });
    dom.handsfree.addEventListener('click', () => turn.setHandsfree(!prefs.get('handsfree')));
    dom.newConversation.addEventListener('click', () => this.#newConversation());
    dom.timings.addEventListener('toggle', () => {
      if (dom.timings.open) this.#loadTimings();
    });
  }

  open() {
    this.render();
    this.dom.sheet.showModal();
    if (this.dom.timings.open) this.#loadTimings();
  }

  close() {
    this.dom.sheet.close();
  }

  render() {
    this.dom.handsfree.setAttribute('aria-checked', String(this.prefs.get('handsfree')));
  }

  setFooter(text) {
    setText(this.dom.foot, text);
  }

  async #newConversation() {
    const title = this.dom.newConversationTitle;
    if (Date.now() > this.#confirmUntil) {
      this.#confirmUntil = Date.now() + CONFIRM_MS;
      setText(title, 'Tap again to start afresh');
      setTimeout(() => {
        if (Date.now() >= this.#confirmUntil) setText(title, 'New conversation');
      }, CONFIRM_MS);
      return;
    }
    this.#confirmUntil = 0;
    setText(title, 'New conversation');
    if (await this.onNewConversation()) this.close();
  }

  async #loadTimings() {
    const body = this.dom.timingsBody;
    body.setAttribute('aria-busy', 'true');
    try {
      const turns = await fetchTimings(TURNS_SHOWN);
      body.replaceChildren(...(turns.length ? turns.map(turnTable) : [h('p', { class: 'muted', text: 'No turns timed yet.' })]));
    } catch (err) {
      body.replaceChildren(h('p', { class: 'muted', text: `Couldn’t load timings: ${err.message}` }));
    } finally {
      body.removeAttribute('aria-busy');
    }
  }
}

/** One turn's marks. The Mac's are times since the mic was offered; the phone's are durations it measured. */
function turnTable({ turn, at, marks }) {
  const when = at ? new Date(at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '';
  return h('section', { class: 'timing-turn' },
    h('h3', {}, h('span', { text: when }), h('span', { class: 'muted', text: turn })),
    h('table', {},
      h('tbody', {}, marks.map((m) => h('tr', { dataset: { source: m.source ?? 'mac' } },
        h('th', { scope: 'row' }, m.name, extras(m) ? h('small', { text: extras(m) }) : null),
        h('td', { text: m.ms == null ? '' : m.source === 'phone' ? fmtMs(m.ms) : `+${fmtMs(m.ms)}` }),
        h('td', { class: 'source', text: m.source ?? 'mac' }))))));
}

function extras(mark) {
  return Object.entries(mark)
    .filter(([key]) => !['name', 'ms', 'source', 'at'].includes(key))
    .map(([key, value]) => `${key} ${value}`)
    .join(' · ');
}
