from pathlib import Path

from voice.lexicon import Lexicon, normalize, say_int, say_ordinal, say_year, translate_script


FRAMES = {"to record": "tə ɹᵻkˈɔːɹd", "the record": "ðə ɹˈɛkɚd", "had read": "hæd ɹˈɛd", "a cat": "ɐ kˈæt"}


def no_tags(tokens):
    return ["" for _ in tokens]


class FakeEspeak(Lexicon):
    """espeak stands in as '<word>' (a few frames are real), so tests need neither espeak-ng nor NLTK."""

    def __init__(self, path, tagger=no_tags):
        super().__init__(path, tagger)

    def _espeak(self, words):
        return [FRAMES.get(w, " ".join(f"<{x}>" for x in w.split())) if " " in w else {"record": "ɹˈɛkɚd", "read": "ɹˈiːd", "a": "ˈeɪ"}.get(w, f"<{w}>") for w in words]


def test_numbers_dates_and_symbols_become_words():
    assert say_int(2116) == "two thousand one hundred sixteen"
    assert say_ordinal(21) == "twenty-first" and say_ordinal(12) == "twelfth" and say_ordinal(40) == "fortieth"
    assert say_year(2026) == "twenty twenty-six" and say_year(2007) == "two thousand seven" and say_year(1905) == "nineteen oh five"
    assert normalize("costs $20, the 21st") == "costs twenty dollars, the twenty-first"
    assert normalize("64% of 400,000") == "sixty-four percent of four hundred thousand"
    assert normalize("a 1.5B model in 1979") == "a one point five B model in nineteen seventy-nine"
    assert normalize("R&D") == "R and D"
    assert normalize("see SKILL.md and e.g. this") == "see SKILL dot md and e dot g. this"
    assert normalize("in .NET and Java. Then") == "in dot NET and Java. Then"


def test_every_word_goes_through_the_lexicon(tmp_path):
    lex = FakeEspeak(tmp_path / "lex.tsv")
    assert lex.translate("The LLMs, by Fowler.") == "<the> ˈɛl ˈɛl ˈɛmz, <by> <fowler>."
    assert sorted(lex.added) == ["LLMs", "by", "fowler", "the"]
    assert lex.entries["LLMs"][1] == "rule" and lex.entries["fowler"][1] == "espeak"


def test_acronyms_spell_and_possessives_take_z(tmp_path):
    lex = FakeEspeak(tmp_path / "lex.tsv")
    assert lex.translate("AI's GPT") == "ˈeɪ ˈaɪz dʒˈiː pˈiː tˈiː"


def test_lexicon_persists_and_corrections_are_never_overwritten(tmp_path):
    path = tmp_path / "lex.tsv"
    lex = FakeEspeak(path)
    lex.translate("readme")
    lex.set("README", "ɹˈiːd mˌiː", "claude")
    again = FakeEspeak(path)
    again.learn(["README", "readme"])
    assert again.entries["README"] == ("ɹˈiːd mˌiː", "claude", again.entries["README"][2])
    assert again.translate("README") == "ɹˈiːd mˌiː" and again.added == []


def test_translation_is_deterministic_and_keeps_pauses(tmp_path):
    lex = FakeEspeak(tmp_path / "lex.tsv")
    script = ["Stage 1.", "@@", "Hello there!", "@"]
    first = translate_script(script, lex)
    assert first == translate_script(script, FakeEspeak(tmp_path / "lex.tsv"))
    assert first[1] == "@@" and first[3] == "@" and first[0] == "<stage> <one>."


def test_decades_and_joined_names():
    assert normalize("since the 1990s and the '80s") == "since the nineteen nineties and the eighties"
    lex = FakeEspeak.__new__(FakeEspeak)
    Lexicon.__init__(lex, Path("/nonexistent/lex.tsv"), no_tags)
    assert lex.split("YouGov") == ["You", "Gov"] and lex.split("ChatGPT") == ["Chat", "GPT"]
    assert lex.split("LLMs") == ["LLMs"] and lex.split("Fowler") == ["Fowler"]
    lex.entries["arXiv"] = ("ˈɑːɹkaɪv", "claude", "")
    assert lex.split("arXiv") == ["arXiv"]


def test_context_forms_are_stored_and_chosen_by_tag(tmp_path):
    tags = {"I will record the record .": "PRP MD VB DT NN .", "I have read a record .": "PRP VBP VBN DT NN .",
            "I will record it .": "PRP MD VB PRP ."}
    lex = FakeEspeak(tmp_path / "lex.tsv", lambda toks: tags[" ".join(toks)].split())
    assert lex.translate("I will record the record.") == "<i> <will> ɹᵻkˈɔːɹd <the> ɹˈɛkɚd."
    assert lex.entries["record@VERB"][0] == "ɹᵻkˈɔːɹd" and "record@NOUN" not in lex.entries
    assert lex.translate("I have read a record.") == "<i> <have> ɹˈɛd ɐ ɹˈɛkɚd."
    lex.set("record@VERB", "ɹɪkˈɔːɹd", "human")
    assert lex.translate("I will record it.") == "<i> <will> ɹɪkˈɔːɹd <it>."
