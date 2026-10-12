"""Check files bound for the public zpkt repo: no copied tutorial content, no rig details.

    run public_check.py docs/techniques/<slug>.md docs/techniques/<slug>.recipe.json \\
        --transcript ~/_agent_scratch/tutorials/<id>/transcript.parakeet.json \\
        --captions ~/_agent_scratch/tutorials/<id>/src/<id>.en.json3

Flags (exit 1 if any):
- copied words: any run of --n (default 6) words that also occurs in the transcript or captions.
  Common phrases can trip it; rephrase anyway, it costs nothing.
- quotes over five words, in double, curly or angle quote marks. Quotes that are not the
  tutorial's words are fine with --allow (repeatable): its title in the credit, Anthony's verdict;
- media: links or paths to images, video, audio or caption files (frames and crops stay private);
- rig details: tailnet host names, Tailscale addresses, mounted volumes and Keychain lookups.
  Names that are private in themselves (rig folders, devices, item names) go in a --deny FILE kept
  outside git (one per line), so the list itself never becomes public.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

QUOTE_RE = re.compile(r'"([^"\n]+)"|“([^”\n]+)”|‘([^’\n]+)’|«([^»\n]+)»')


def quotes(text: str) -> list[str]:
    return [next(g for g in groups if g) for groups in QUOTE_RE.findall(text)]
MEDIA_RE = re.compile(r"[\w./~-]+\.(png|jpe?g|gif|webp|mp4|mov|webm|wav|aiff?|flac|mp3|m4a|json3|vtt|srt)\b", re.I)
RIG = [
    (re.compile(r"\b[a-z0-9-]+\.[a-z0-9-]+\.ts\.net\b", re.I), "tailnet host name"),
    (re.compile(r"\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"), "Tailscale address"),
    (re.compile(r"\bfd7a:115c:a1e0:", re.I), "Tailscale IPv6 address"),
    (re.compile(r"/Volumes/"), "mounted volume path"),
    (re.compile(r"find-generic-password|security\s+add-generic"), "Keychain lookup"),
]
ALLOWED_MEDIA = re.compile(r"^/audio/skrng/|^https?://", re.I)


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower().replace("’", "'"))


def ngrams(ws: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(ws[i:i + n]) for i in range(len(ws) - n + 1)}


def source_words(path: Path) -> list[str]:
    d = json.loads(path.read_text())
    if "words" in d:  # transcribe.py output
        return words(" ".join(w["text"] for w in d["words"]))
    if "events" in d:  # YouTube json3
        return words(" ".join(s.get("utf8", "") for e in d["events"] for s in e.get("segs", [])))
    if isinstance(d, list):  # caption words
        return words(" ".join(w.get("text", "") for w in d))
    raise SystemExit(f"{path}: not a transcript, json3 or word list")


def file_text(path: Path) -> str:
    text = path.read_text()
    if path.suffix in (".json", ".jsonl"):
        def walk(v):
            if isinstance(v, str):
                yield v
            elif isinstance(v, dict):
                for x in v.values():
                    yield from walk(x)
            elif isinstance(v, list):
                for x in v:
                    yield from walk(x)
        lines = [ln for ln in text.splitlines() if ln.strip()]
        docs = [json.loads(ln) for ln in lines] if path.suffix == ".jsonl" else [json.loads(text)]
        return "\n".join(x for d in docs for x in walk(d))
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--transcript", action="append", default=[], help="transcribe.py JSON (repeatable)")
    ap.add_argument("--captions", action="append", default=[], help="json3 or caption-word JSON (repeatable)")
    ap.add_argument("--n", type=int, default=6, help="words in a row that count as copied")
    ap.add_argument("--deny", help="private word list (one per line), kept outside git")
    ap.add_argument("--allow", action="append", default=[], help="a quoted text that is fine, e.g. the title")
    a = ap.parse_args()

    src: set[tuple[str, ...]] = set()
    for p in a.transcript + a.captions:
        if not Path(p).expanduser().exists():
            print(f"warning: no source {p}; copied words are checked against the others only")
            continue
        src |= ngrams(source_words(Path(p).expanduser()), a.n)
    deny = []
    if a.deny and Path(a.deny).expanduser().exists():
        deny = [w.strip() for w in Path(a.deny).expanduser().read_text().splitlines() if w.strip() and not w.startswith("#")]
    elif a.deny:
        print(f"warning: no deny list at {a.deny}; private names are not checked")
    findings = []
    for f in a.files:
        path = Path(f)
        text = file_text(path)
        ws = words(text)
        hits = sorted({" ".join(g) for g in ngrams(ws, a.n) & src})
        findings += [(f, "copied words", h) for h in hits]
        findings += [(f, "quote over five words", q[:80]) for q in quotes(text)
                     if len(q.split()) > 5 and q.strip() not in a.allow]
        findings += [(f, "media", m.group(0)) for m in MEDIA_RE.finditer(text) if not ALLOWED_MEDIA.match(m.group(0))]
        findings += [(f, what, m.group(0)) for rx, what in RIG for m in rx.finditer(text)]
        findings += [(f, "private word", w) for w in deny if w.lower() in text.lower()]
    for f, what, detail in findings:
        print(f"{f}: {what}: {detail}")
    checked = f"{len(a.files)} file(s), {len(src)} source {a.n}-grams" if src else f"{len(a.files)} file(s), no source text"
    print(f"public_check: {len(findings)} finding(s) in {checked}")
    sys.exit(1 if findings else 0)


if __name__ == "__main__":
    main()
