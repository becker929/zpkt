// Fitting text into a control. SVG text cannot be measured without a DOM (snapshots are plain strings), so widths
// are estimated per character and long text is cut with an ellipsis. Pure functions, no DOM.

const seg = typeof Intl !== 'undefined' && Intl.Segmenter ? new Intl.Segmenter(undefined, { granularity: 'grapheme' }) : null;
/** What a reader sees as characters (an emoji with its modifiers is one). */
export const chars = (s) => (seg ? Array.from(seg.segment(s), (x) => x.segment) : [...s]);

// Width of one character in ems: wide scripts and emoji a full em, capitals and digits more than lower case.
function em(ch, mono) {
  const cp = ch.codePointAt(0);
  if (cp >= 0x1f000 || (cp >= 0x2600 && cp <= 0x27bf) || ch.length > 2) return 1.4;   // emoji
  if (cp >= 0x1100 && (cp <= 0x115f || (cp >= 0x2e80 && cp <= 0xa4cf) || (cp >= 0xac00 && cp <= 0xd7a3) || (cp >= 0xf900 && cp <= 0xfaff) || (cp >= 0xfe30 && cp <= 0xfe4f) || (cp >= 0xff00 && cp <= 0xff60))) return 1.05;
  if (cp >= 0x2190 && cp <= 0x2bff) return 1.1;   // arrows, symbols
  if (mono) return 0.61;
  if (/[MWmw@%]/.test(ch)) return 0.9;
  if (/[A-Z0-9#&—]/.test(ch)) return 0.67;
  if (/[il.,:;'|!·\- ]/.test(ch)) return 0.32;
  return 0.56;
}

/** Estimated width in px of `s` at font size `px`. */
export const widthOf = (s, px, mono = false) => chars(s).reduce((w, ch) => w + em(ch, mono), 0) * px;

/** `s`, cut with an ellipsis if it would be wider than `max` px. */
export function fit(s, max, px, mono = false) {
  if (widthOf(s, px, mono) <= max) return s;
  const cs = chars(s);
  let w = em('…', mono) * px, out = '';
  for (const ch of cs) {
    w += em(ch, mono) * px;
    if (w > max) break;
    out += ch;
  }
  return out.trimEnd() + '…';
}
