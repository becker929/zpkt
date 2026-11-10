// Passing notices: the Mac's `notice` messages and the page's own (offline, mic blocked), shown for
// a few seconds under the top bar. Kept notices arrive as chat messages instead.
import { h } from './dom.js';
import { icon } from './icons.js';

const SHOW_MS = 5000;
const MAX_SHOWN = 3;

export class Toasts {
  constructor(root) {
    this.root = root;
  }

  /** `action` = {label, run}: a button in the toast (for example, to resume audio). */
  show(text, level = 'info', { ms = SHOW_MS, action = null, key = null } = {}) {
    if (key) this.root.querySelector(`[data-key="${key}"]`)?.remove();
    const toast = h('div', { class: 'toast', role: level === 'error' ? 'alert' : 'status', dataset: { level, ...(key && { key }) } },
      h('span', { class: 'toast-text', text }),
      action && h('button', { class: 'toast-action', type: 'button', text: action.label, onclick: () => {
        action.run();
        toast.remove();
      } }),
      h('button', { class: 'toast-close', type: 'button', 'aria-label': 'Dismiss', onclick: () => toast.remove() }, icon('close')));
    this.root.append(toast);
    while (this.root.children.length > MAX_SHOWN) this.root.firstElementChild.remove();
    if (ms) setTimeout(() => toast.remove(), ms);
    return toast;
  }

  dismiss(key) {
    this.root.querySelector(`[data-key="${key}"]`)?.remove();
  }
}
