"""Text to phonemes, deterministically, through a lexicon that grows.

Every word goes through the lexicon; nothing is left to the model's own guess at spelling.
A word not yet in the lexicon is phonemized once by espeak-ng (the same G2P Kokoro uses) and
saved with source "espeak". Any entry can be corrected with `voice lexicon WORD PHONEMES`;
a correction is never overwritten. Its source says who made it: "human" or "claude". The lexicon is a sorted TSV in the repo, so its
growth shows up in diffs.

Context: when a word sounds different after "the", "to", "they" or "had" (record, read, live, uses),
espeak's form in that frame is stored as WORD@NOUN, @VERB, @VERBS or @PAST, and determiners like "a"
get @DET (ɐ, not the letter). NLTK's part-of-speech tag for each word in its sentence picks the form.
Joined names (YouGov, ChatGPT) are read as their parts unless a correction names the whole word.

Rules turn what is not a word into words first: numbers, years, ordinals, percents, money,
decimals, decades, symbols, file names, and runs of capitals (spelled as letters unless corrected).

    voice phonemes script.txt -o script.phon       # translate a script, growing the lexicon
    voice read script.txt -o out.mp3                # translate, then speak from phonemes only
"""
from __future__ import annotations

import datetime
import os
import re
import unicodedata
from pathlib import Path

LEXICON = Path(os.environ.get("VOICE_LEXICON", Path(__file__).resolve().parents[2] / "lexicon" / "en-us.tsv"))
SOURCES = ("human", "claude", "rule", "espeak")    # who set an entry: a person, an agent's correction, a rule, espeak

# Letter names, used to spell runs of capitals. Kokoro's vocab takes these IPA symbols.
LETTERS = {
    "a": "ˈeɪ", "b": "bˈiː", "c": "sˈiː", "d": "dˈiː", "e": "ˈiː", "f": "ˈɛf", "g": "dʒˈiː",
    "h": "ˈeɪtʃ", "i": "ˈaɪ", "j": "dʒˈeɪ", "k": "kˈeɪ", "l": "ˈɛl", "m": "ˈɛm", "n": "ˈɛn",
    "o": "ˈoʊ", "p": "pˈiː", "q": "kjˈuː", "r": "ˈɑːɹ", "s": "ˈɛs", "t": "tˈiː", "u": "jˈuː",
    "v": "vˈiː", "w": "dˈʌbəljuː", "x": "ˈɛks", "y": "wˈaɪ", "z": "zˈiː",
}

_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_ORD = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth", "nine": "ninth", "twelve": "twelfth"}
_SYMBOLS = {"&": " and ", "+": " plus ", "=": " equals ", "@": " at ", "#": " number ", "/": " slash ", "×": " times ", "°": " degrees "}


def say_int(n: int) -> str:
    if n < 0:
        return "minus " + say_int(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else "")
    for size, name in ((10**12, "trillion"), (10**9, "billion"), (10**6, "million"), (1000, "thousand"), (100, "hundred")):
        if n >= size:
            head, rest = divmod(n, size)
            return say_int(head) + " " + name + (" " + say_int(rest) if rest else "")
    raise AssertionError(n)


def say_ordinal(n: int) -> str:
    words = say_int(n)
    head, _, last = words.rpartition(" ")
    pre, dash, tail = last.rpartition("-")
    if tail in _ORD:
        tail = _ORD[tail]
    elif tail.endswith("y"):
        tail = tail[:-1] + "ieth"
    else:
        tail += "th"
    return (head + " " if head else "") + pre + dash + tail


def say_year(n: int) -> str:
    if 2000 <= n <= 2009:
        return say_int(n)
    hi, lo = divmod(n, 100)
    if lo == 0:
        return say_int(hi) + " hundred"
    return say_int(hi) + " " + (("oh " + _ONES[lo]) if lo < 10 else say_int(lo))


def plural(words: str) -> str:
    """nineteen ninety -> nineteen nineties; nineteen hundred -> nineteen hundreds."""
    return words[:-1] + "ies" if words.endswith("y") else words + "s"


def normalize(text: str) -> str:
    """Rewrite everything that is not a plain word as words, by fixed rules."""
    t = unicodedata.normalize("NFKC", text)
    t = t.replace("’", "'").replace("‘", "'").replace("–", " to ").replace("—", ", ")
    t = re.sub(r"\b(1[1-9]\d0|20\d0)s\b", lambda m: plural(say_year(int(m.group(1)))), t)   # 1990s
    t = re.sub(r"(?:'|\b)([2-9]0)s\b", lambda m: plural(say_int(int(m.group(1)))), t)               # '90s, 90s
    num = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    t = re.sub(r"\$" + num, lambda m: m.group(1) + " dollars", t)
    t = re.sub(num + r"\s?%", lambda m: m.group(1) + " percent", t)
    t = re.sub(r"\b(\d+)(st|nd|rd|th)\b", lambda m: say_ordinal(int(m.group(1))), t)
    t = re.sub(r"(?<=\d)(?=[A-Za-z])|(?<=[A-Za-z])(?=\d)", " ", t)    # 1.5B -> 1.5 B, GPT4 -> GPT 4
    t = re.sub(r"(?<![\d.,])(1[1-9]\d\d|20\d\d)(?![\d,.]\d)", lambda m: say_year(int(m.group(1))), t)
    t = re.sub(r"(\d+)\.(\d+)", lambda m: say_int(int(m.group(1))) + " point " + " ".join(_ONES[int(d)] for d in m.group(2)), t)
    t = re.sub(r"\d{1,3}(?:,\d{3})+|\d+", lambda m: " " + say_int(int(m.group(0).replace(",", ""))) + " ", t)
    t = re.sub(r"(?<=[A-Za-z])\.(?=[A-Za-z])", " dot ", t)          # SKILL.md -> SKILL dot md
    t = re.sub(r"(?<![\w.])\.(?=[A-Za-z])", "dot ", t)                # .NET -> dot NET
    for sym, word in _SYMBOLS.items():
        t = t.replace(sym, word)
    return re.sub(r"[ \t]+", " ", t).strip()


_TOKEN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)*|[.,;:!?…“”\"()]")
_CAMEL = re.compile(r"[A-Z]?[a-z]+(?:'[a-z]+)?|[A-Z]+(?![a-z])(?:'s)?")
CORRECTED = ("human", "claude")

# Context: espeak says a word differently after "the", "to", "they" or "had" (record, read, live,
# uses, wind...), and "a" alone is the letter. Each frame's form is stored as WORD@CONTEXT when it
# differs from the bare word, and a part-of-speech tag picks the frame.
CONTEXTS = {"NOUN": ("the {}", -1), "VERB": ("to {}", -1), "VERBS": ("they {}", -1), "PAST": ("had {}", -1), "DET": ("{} cat", 0)}
DETERMINERS = {"a", "an", "the", "this", "that", "these", "those", "some", "any", "no", "every", "each", "all",
               "both", "another", "either", "neither", "half", "such", "what", "which", "whatever"}
_TAG = {"NN": "NOUN", "NNS": "NOUN", "NNP": "NOUN", "NNPS": "NOUN", "JJ": "NOUN", "JJR": "NOUN", "JJS": "NOUN",
        "VB": "VERB", "VBP": "VERB", "VBG": "VERB", "VBZ": "VERBS", "VBD": "PAST", "VBN": "PAST", "DT": "DET"}


def tag(tokens: list[str]) -> list[str]:
    """Penn Treebank tags from NLTK's averaged perceptron (deterministic)."""
    import nltk
    try:
        return [t for _, t in nltk.pos_tag(tokens)]
    except LookupError:
        nltk.download("averaged_perceptron_tagger_eng", quiet=True)
        return [t for _, t in nltk.pos_tag(tokens)]


class Lexicon:
    def __init__(self, path: Path = LEXICON, tagger=None):
        self.path = Path(path)
        self.tagger = tagger or tag
        self.entries: dict[str, tuple[str, str, str]] = {}      # key -> (phonemes, source, added)
        self.added: list[str] = []
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line and not line.startswith("#"):
                    key, ph, src, day = (line.split("\t") + ["", "", ""])[:4]
                    self.entries[key] = (ph, src, day)
        self._tok = None

    @staticmethod
    def key(word: str) -> str:
        """Lowercase, except words with capitals after the first letter (acronyms, brands)."""
        return word if any(c.isupper() for c in word[1:]) else word.lower()

    def _espeak(self, words: list[str]) -> list[str]:
        if self._tok is None:
            from kokoro_onnx.tokenizer import Tokenizer
            self._tok = Tokenizer()
        return [self._tok.phonemize(w) for w in words]

    @staticmethod
    def _split_acronym(word: str) -> tuple[str, bool] | None:
        """'LLM' -> ('LLM', False); 'LLMs', "AI's" -> (core, True); anything else -> None."""
        core, plural = word, False
        for tail in ("'s", "s"):
            if word.endswith(tail) and len(word) > len(tail) + 1 and word[: -len(tail)].isupper():
                core, plural = word[: -len(tail)], True
                break
        return (core, plural) if len(core) >= 2 and core.isalpha() and core.isupper() else None

    def _spell(self, word: str) -> str:
        """Runs of capitals: letter names, with a plural or possessive s as /z/."""
        core, plural = self._split_acronym(word)
        return " ".join(LETTERS[c] for c in core.lower()) + ("z" if plural else "")

    def _acronym(self, word: str) -> bool:
        return self._split_acronym(word) is not None

    def corrected(self, key: str) -> bool:
        return key in self.entries and self.entries[key][1] in CORRECTED

    def split(self, token: str) -> list[str]:
        """Joined names (YouGov, ChatGPT) become their parts, unless a correction names the whole."""
        if not token[0].isalpha() or self.corrected(self.key(token)) or self._acronym(token):
            return [token]
        parts = _CAMEL.findall(token)
        return parts if len(parts) > 1 and "".join(parts) == token else [token]

    def _contexts(self, keys: list[str], day: str) -> None:
        """Store each frame's form of these words where it differs from the bare word."""
        for ctx, (frame, at) in CONTEXTS.items():
            keys_ = [k for k in keys if ctx != "DET" or k in DETERMINERS]
            phrases = [frame.format(k) for k in keys_]
            for k, ph in zip(keys_, self._espeak(phrases)):
                words = ph.split()
                if len(words) == len(frame.split()) and words[at] != self.entries[k][0]:
                    self.entries[f"{k}@{ctx}"] = (words[at], "espeak", day)

    def learn(self, words: list[str]) -> None:
        """Add every unknown word, by rule (capital runs) or espeak with its context forms, and save."""
        day = datetime.date.today().isoformat()
        todo = sorted({self.key(w) for w in words} - self.entries.keys())
        if not todo:
            return
        rules = [k for k in todo if self._acronym(k)]
        for k in rules:
            self.entries[k] = (self._spell(k), "rule", day)
        rest = [k for k in todo if k not in rules]
        for k, ph in zip(rest, self._espeak(rest)):
            self.entries[k] = (ph, "espeak", day)
        self._contexts(rest, day)
        self.added += todo
        self.save()

    def backfill(self) -> int:
        """Context forms for espeak words learned before contexts existed."""
        have = {k.split("@")[0] for k in self.entries if "@" in k}
        keys = [k for k, (_, src, _) in self.entries.items() if "@" not in k and src == "espeak" and k not in have]
        self._contexts(keys, datetime.date.today().isoformat())
        self.save()
        return len(keys)

    def lookup(self, token: str, tag_: str = "") -> str:
        k = self.key(token)
        base = self.entries[k]
        ctx = _TAG.get(tag_)
        variant = self.entries.get(f"{k}@{ctx}") if ctx else None
        if variant and (base[1] not in CORRECTED or variant[1] in CORRECTED):
            return variant[0]
        return base[0]

    def set(self, word: str, phonemes: str, source: str = "human") -> None:
        """Correct a word, or one context of it as WORD@NOUN, WORD@VERB, WORD@VERBS, WORD@PAST or WORD@DET."""
        word, _, ctx = word.partition("@")
        key = self.key(word) + (f"@{ctx.upper()}" if ctx else "")
        self.entries[key] = (phonemes, source, datetime.date.today().isoformat())
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        head = "# word[@context]\tphonemes\tsource (human, claude, rule or espeak)\tadded\n"
        body = "".join(f"{k}\t{ph}\t{src}\t{day}\n" for k, (ph, src, day) in sorted(self.entries.items(), key=lambda kv: (kv[0].lower(), kv[0])))
        self.path.write_text(head + body, encoding="utf-8")

    def translate(self, text: str) -> str:
        """One line of text to one line of phonemes. Every word comes from the lexicon, in context."""
        tokens = [p for t in _TOKEN.findall(normalize(text)) for p in self.split(t)]
        self.learn([t for t in tokens if t[0].isalpha()])
        out: list[str] = []
        for t, tg in zip(tokens, self.tagger(tokens) if tokens else []):
            if t[0].isalpha():
                out.append(self.lookup(t, tg))
            elif out:
                out[-1] += t.replace('"', "")
        return " ".join(p for p in out if p)


def translate_script(lines: list[str], lexicon: Lexicon | None = None) -> list[str]:
    """Pause markers ('@', '@@') pass through; every other line becomes phonemes."""
    lex = lexicon or Lexicon()
    return [line if line.strip() in ("@", "@@", "") else lex.translate(line) for line in lines]
