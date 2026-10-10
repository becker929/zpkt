// A screenshot pair, full size: the screen or the zoom. Pinch-zoom is the browser's own (the page
// never disables user scaling).
import { setText } from './dom.js';

const PIXELATED_FROM = 2;     // the zoom is native pixels: enlarged this much or more, keep its edges sharp

export class Lightbox {
  #shot = null;
  #which = 'full';

  constructor(dom) {
    this.dom = dom;
    dom.dialog.addEventListener('click', (e) => {
      const tab = e.target.closest('[data-which]');
      if (tab) this.#show(tab.dataset.which);
      else if (e.target.closest('[data-close]') || e.target === dom.dialog || e.target === dom.stage) this.close();
    });
    dom.dialog.addEventListener('close', () => {
      this.#shot = null;
      dom.img.removeAttribute('src');
    });
    dom.img.addEventListener('load', () => this.#sharpen());
    addEventListener('resize', () => this.#sharpen());
  }

  /** `data` is a shots message's data; `which` is 'full' or 'zoom'. */
  open(data, which = 'full') {
    this.#shot = data;
    setText(this.dom.caption, data.caption ?? '');
    this.#show(which);
    if (!this.dom.dialog.open) this.dom.dialog.showModal();
  }

  close() {
    if (this.dom.dialog.open) this.dom.dialog.close();
  }

  #show(which) {
    const ref = this.#shot?.[which];
    if (!ref?.url) return;
    this.#which = which;
    const { img, dialog } = this.dom;
    if (ref.w && ref.h) {
      img.width = ref.w;
      img.height = ref.h;
    }
    img.classList.remove('pixelated');
    img.src = ref.url;
    img.alt = which === 'full' ? 'The Mac’s screen' : 'A zoom on what changed';
    for (const tab of dialog.querySelectorAll('[role="tab"]')) {
      tab.setAttribute('aria-selected', String(tab.dataset.which === which));
    }
  }

  #sharpen() {
    const { img } = this.dom;
    if (!this.#shot || !img.naturalWidth) return;
    const scale = (img.clientWidth * devicePixelRatio) / img.naturalWidth;
    img.classList.toggle('pixelated', this.#which === 'zoom' && scale >= PIXELATED_FROM);
  }
}
