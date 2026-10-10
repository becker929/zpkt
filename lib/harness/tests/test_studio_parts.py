"""studio's parts on their own: the store, spoken commands, cutting text for speech, tool descriptions, saliency."""

import numpy as np
import pytest

from harness.studio import intents, shots
from harness.studio.activity import describe
from harness.studio.model import Kind, Message, Prefs, ShotLevel
from harness.studio.speech import Segmenter
from harness.studio.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path)
    yield s
    s.close()


def test_messages_page_backwards_and_updates_bump_rev(store):
    conv = store.conversation()
    for i in range(7):
        store.add(Message(Kind.USER, {"text": f"m{i}"}, conversation=conv.id))
    other = store.new_conversation()
    store.add(Message(Kind.USER, {"text": "elsewhere"}, conversation=other.id))
    assert store.conversation().id == other.id                       # the newest is current

    page, more = store.page(conv.id, None, 3)
    assert [m.data["text"] for m in page] == ["m4", "m5", "m6"] and more
    page2, more2 = store.page(conv.id, page[0].seq, 3)
    assert [m.data["text"] for m in page2] == ["m1", "m2", "m3"] and more2
    page3, more3 = store.page(conv.id, page2[0].seq, 3)
    assert [m.data["text"] for m in page3] == ["m0"] and not more3

    msg = page[-1]
    msg.data["text"] = "edited"
    store.update(msg)
    again = store.get(msg.seq)
    assert again.rev == 1 and again.data["text"] == "edited"
    assert store.last(conv.id, Kind.USER).seq == msg.seq


def test_media_is_content_addressed_and_names_are_checked(store):
    a = store.put_media(b"abc", "mp3")
    b = store.put_media(b"abc", "mp3")
    assert a == b and a.url.startswith("/studio/media/") and a.type == "audio/mpeg"
    name = a.url.rsplit("/", 1)[1]
    assert store.media_file(name).read_bytes() == b"abc"
    assert store.media_file("../studio.sqlite3") is None and store.media_file("x" * 64 + ".mp3") is None
    shot = store.put_media(b"img", "webp", w=10, h=5)
    assert shot.wire()["w"] == 10 and shot.wire()["h"] == 5


def test_timings_group_by_turn_newest_first(store):
    store.mark("c", "t1", "listen", 0)
    store.mark("c", "t1", "stop_word", 2100.5, extra={"stt_ms": 80})
    store.mark("c", "t2", "listen", 0)
    turns = store.timings(5)
    assert [t["turn"] for t in turns] == ["t2", "t1"]
    assert turns[1]["marks"][1] == {"name": "stop_word", "ms": 2100.5, "source": "mac", "at": turns[1]["marks"][1]["at"],
                                    "stt_ms": 80}


@pytest.mark.parametrize("text,expected", [
    ("play again", ("play", 1)),
    ("Play it again.", ("play", 1)),
    ("loop that three times", ("play", 3)),
    ("Okay, loop that 4 times please", ("play", 4)),
    ("play it twice", ("play", 2)),
    ("three times", ("play", 3)),
    ("one more time", ("play", 1)),
    ("again", ("play", 1)),
    ("loop that 99 times", ("play", intents.MAX_LOOPS)),
    ("stop", ("stop", 0)),
    ("stop the music", ("stop", 0)),
    ("play again but with more reverb on the snare", None),
    ("make the kick louder", None),
    ("play the B version", None),
    ("", None),
])
def test_spoken_commands(text, expected):
    got = intents.parse(text)
    assert (got.action, got.loops) == expected if expected else got is None


def speak(chunks):
    seg = Segmenter()
    out = []
    for c in chunks:
        out += seg.feed(c)
    return out + seg.flush()


def test_text_is_cut_into_speakable_pieces_however_it_streams():
    text = ("Okay, rendering the B version now. It has 3.5 dB more drive, e.g. on the kick. Here it is:\n"
            "```python\nprint('x')\n```\nDone! Want more?")
    expected = ["Okay, rendering the B version now.", "It has 3.5 dB more drive, e.g. on the kick.", "Here it is:",
                "Done!", "Want more?"]
    assert speak([text]) == expected
    assert speak(list(text)) == expected                              # one character at a time
    assert speak([text[i:i + 7] for i in range(0, len(text), 7)]) == expected


def test_first_piece_is_short_and_long_sentences_are_split():
    first = speak(["I listened to both versions, and the second one has a clearer low end overall."])
    assert first[0] == "I listened to both versions," and len(first) == 2
    long = speak(["word " * 80])
    assert len(long) >= 2 and all(len(p) <= Segmenter.MAX_CHARS for p in long)
    assert speak(["```\nonly code\n```"]) == []


def test_tool_calls_in_a_few_words():
    assert describe("Bash", {"command": "uv run x.py", "description": "Render the A/B"}) == "Render the A/B"
    assert describe("Read", {"file_path": "/a/b/plan.json"}) == "Read plan.json"
    assert describe("mcp__studio__play_music", {"loops": 3}) == "Play it 3×"
    assert describe("Skill", {"skill": "render-plan"}) == "Use the render-plan skill"


def test_prefs_parse_with_defaults():
    p = Prefs.parse({"autoplay": False, "shots": "firehose"})
    assert not p.autoplay and p.shots is ShotLevel.FIREHOSE and p.handsfree
    assert Prefs.parse(None).shots is ShotLevel.MAJOR
    assert Prefs.parse({"shots": "bogus"}).shots is ShotLevel.MAJOR


def screen(h=1080, w=1920):
    rng = np.random.default_rng(0)
    return (rng.integers(0, 40, (h, w, 3))).astype(np.uint8)


def test_salient_rect_frames_the_biggest_change_at_16_by_9():
    a = screen()
    b = a.copy()
    b[600:700, 1000:1300] = 255                                       # a panel lit up
    b[5:20, 1800:1900] = 255                                          # the menu-bar clock: ignored
    x, y, w, h = shots.salient_rect(a, b)
    assert x <= 1000 and x + w >= 1300 and y <= 600 and y + h >= 700
    assert abs(w / h - 16 / 9) < 0.02 and w >= shots.ZOOM_MIN_W
    assert shots.salient_rect(a, a.copy()) is None
    tiny = a.copy()
    tiny[500:504, 500:504] = 255                                      # a blinking cursor
    assert shots.salient_rect(a, tiny) is None
    hx, hy, hw, hh = shots.salient_rect(None, a, hint=(1900, 1070))   # a hint near the corner stays on screen
    assert hx + hw <= 1920 and hy + hh <= 1080


def test_pairs_are_small_webp():
    a = screen()
    b = a.copy()
    b[100:300, 100:600] = 200
    pair = shots.make_pair(a, b)
    assert pair.changed and pair.ext == "webp" and pair.full_size == (1280, 720)
    assert pair.full[:4] == b"RIFF" and pair.zoom[:4] == b"RIFF"
    assert shots.make_pair(a, a.copy(), require_change=True) is None
