from voice.lexicon import Lexicon, normalize, say_int, say_ordinal, say_year, translate_script


class FakeEspeak(Lexicon):
    """espeak stands in as '<word>', so tests need no espeak-ng and show what was asked."""

    def _espeak(self, words):
        return [f"<{w}>" for w in words]


def test_numbers_dates_and_symbols_become_words():
    assert say_int(2116) == "two thousand one hundred sixteen"
    assert say_ordinal(21) == "twenty-first" and say_ordinal(12) == "twelfth" and say_ordinal(40) == "fortieth"
    assert say_year(2026) == "twenty twenty-six" and say_year(2007) == "two thousand seven" and say_year(1905) == "nineteen oh five"
    assert normalize("costs $20, the 21st") == "costs twenty dollars, the twenty-first"
    assert normalize("64% of 400,000") == "sixty-four percent of four hundred thousand"
    assert normalize("a 1.5B model in 1979") == "a one point five B model in nineteen seventy-nine"
    assert normalize("R&D") == "R and D"
    assert normalize("see SKILL.md and e.g. this") == "see SKILL dot md and e dot g. this"


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
