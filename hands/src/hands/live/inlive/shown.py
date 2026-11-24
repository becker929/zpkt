"""What Live shows for a parameter, and the raw value that shows as a given text.

The LOM takes only raw values, but people and recipes think in what Live shows ("-6 dB", "1.2 kHz", "35 %", "Saw D").
`raw_for` finds the raw value that shows as a text by bisecting `str_for_value` over the parameter's range (Live's
laws are not published), and `set_shown` writes it. `shown_number` reads a shown text as a number in its base unit,
so texts with different prefixes compare ("1.73 kHz" > "900 Hz", "2.5 ms" < "1 s").

Stdlib only, Python 3.11: this file also runs inside Live (hands.live.inlive).
"""

import re

_NUMBER = re.compile(r"\s*([+-]?(?:\d+\.?\d*|\.\d+|inf))\s*([a-zA-Z%]*)")
_SCALE = {"khz": 1e3, "ms": 1e-3}
_STEPS = 40  # halvings of the range: far finer than any display rounds to


def shown_number(text: object) -> float | None:
    """A shown value as a number in its base unit ("1.73 kHz" -> 1730, "2.5 ms" -> 0.0025, "-inf dB" -> -1e9);
    None if the text does not start with a number."""
    m = _NUMBER.match(str(text))
    if not m:
        return None
    if "inf" in m.group(1):
        return -1e9 if m.group(1).startswith("-") else 1e9
    return float(m.group(1)) * _SCALE.get(m.group(2).lower(), 1.0)


def _item_value(p, want: str) -> float | None:  # p: a DeviceParameter
    """A list parameter's raw value for one of its items, by name (exact first, then any case); None if none."""
    items = [str(i) for i in getattr(p, "value_items", ())]
    if want in items:
        return float(p.min) + items.index(want)
    for v in range(int(p.min), int(p.max) + 1):
        if str(p.str_for_value(v)).strip().lower() == want.lower():
            return float(v)
    return None


def raw_for(p, want: object):  # p: a DeviceParameter
    """The raw value at which `p` shows `want`: a text Live shows ("200 Hz", "-6 dB", "35 %"), a list item's name,
    or "min", "max", "current". None if the text cannot be read or found."""
    w = str(want).strip()
    keyword = {"min": p.min, "max": p.max, "current": p.value}.get(w.lower())
    if keyword is not None:
        return keyword
    if p.is_quantized:
        found = _item_value(p, w)
        if found is not None:
            return found
    target = shown_number(w)
    a, b = shown_number(p.str_for_value(p.min)), shown_number(p.str_for_value(p.max))
    if target is None or a is None or b is None:
        return None
    lo, hi, rising = p.min, p.max, b >= a
    for _ in range(_STEPS):
        mid = (lo + hi) / 2.0
        v = shown_number(p.str_for_value(mid))
        if v is None:
            return None
        if (v < target) == rising:
            lo = mid
        else:
            hi = mid
    found = hi if rising else lo  # the end of the last step that shows `want` or more, as Live rounds it
    return float(round(found)) if p.is_quantized else found


def set_shown(p, want: str | float, name: str = "") -> str | None:
    """Set `p` to `want`: a shown text (see raw_for) or a raw number, clamped to the range. Returns None when done,
    else what went wrong as "NAME=WANT? ..." (for a list parameter, its items), so a call can collect them."""
    if not isinstance(want, str):
        p.value = max(p.min, min(p.max, float(want)))
        return None
    value = raw_for(p, want)
    if value is None:
        items = [str(i) for i in getattr(p, "value_items", ())] if p.is_quantized else []
        return f"{name or p.name}={want}? {'|'.join(items) or 'not a value it shows'}"
    p.value = max(p.min, min(p.max, value))
    return None
