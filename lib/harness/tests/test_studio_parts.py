"""studio's parts on their own: the store, spoken commands, cutting text for speech, tool descriptions. Screenshots
have their own: test_studio_shots.py, test_studio_grab.py and test_studio_screens.py."""

import gzip
import json
import re

import pytest

from harness.studio import intents
from harness.studio.activity import describe
from harness.studio.assets import Assets, accepts_gzip
from harness.studio.model import Kind, Message, Prefs, ShotLevel
from harness.studio.protocol import SPEECH, speech_frames
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



# --- timings (plan V1) ------------------------------------------------------------------------------------------------

IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1"
CHROME_IOS = "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/140.0 Mobile/15E148 Safari/604.1"
CHROME_MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"


def test_browsers_and_routes_are_named_for_the_comparison():
    from harness.studio.timing import browser, route
    assert browser(IPHONE) == "safari"
    assert browser(CHROME_IOS) == "safari"            # WebKit underneath: same audio session as Safari
    assert browser(CHROME_MAC) == "chrome"
    assert route("iPhone Microphone") == "phone"
    assert route("Anthony's AirPods Pro") == "bluetooth"
    assert route("CarPlay") == "bluetooth"
    assert route("Default") == "phone"
    assert route("MediaStreamAudioDestinationNode") == "other"
    assert route("") == ""


def test_the_timings_report_compares_first_and_later_turns_browsers_and_routes(store):
    from harness.studio.timing import TurnClock, report
    conv = store.conversation()
    for n, (ua, label, first_words) in enumerate([(IPHONE, "iPhone Microphone", 900), (IPHONE, "AirPods", 400),
                                                   (CHROME_MAC, "Default", 300)], start=1):
        clock = TurnClock(store, conv.id, f"t{n}")
        store.mark(conv.id, f"t{n}", "listen", 0, "mac", {"n": n, "browser": "safari" if "iPhone" in ua else "chrome"})
        store.mark(conv.id, f"t{n}", "first_words", first_words, "mac")
        clock.phone("mic_open", 120 * n, input=label)
    text = report(store.timings(10))
    assert "3 turns" in text
    assert "| first_words (mac) | 900 (1) | 350 (2) |" in text            # first vs later
    assert "| first_words (mac) | 300 (1) | 650 (2) |" in text            # chrome vs safari
    assert "| mic_open (phone) | 240 (1) | 240 (2) |" in text            # bluetooth vs phone



async def test_music_is_a_gapless_mp3_with_every_sample(tmp_path):
    # iPhone Safari can't decode FLAC in Web Audio, so music is an MP3; LAME's gapless header lets a decoder trim
    # the encoder's delay and padding, so the decoded render has exactly its source's length (loops stay exact).
    import shutil
    import subprocess

    import numpy as np
    import soundfile as sf

    from harness.studio import audio

    src = tmp_path / "render.wav"
    x = 0.5 * np.sin(2 * np.pi * 440 * np.arange(44_100) / 44_100)
    sf.write(src, np.stack([x, x], axis=1), 44_100, subtype="PCM_24")
    data, info = await audio.to_mp3(src)
    assert data[:3] == b"ID3" or data[0] == 0xFF
    assert b"Xing" in data[:2000] or b"Info" in data[:2000], "LAME's gapless header"
    assert (info.rate, info.channels) == (44_100, 2) and len(data) < 44_100 * 2 * 2 / 4   # under a quarter of the WAV
    if shutil.which("ffmpeg"):
        (tmp_path / "r.mp3").write_bytes(data)
        pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(tmp_path / "r.mp3"), "-f", "s16le", "-"],
                             capture_output=True, check=True).stdout
        assert len(pcm) // 4 == 44_100                     # ffmpeg trims by the header, as the browsers do


def test_speech_goes_out_in_short_frames():
    pcm = bytes(range(256)) * 375                  # 2 s at 24 kHz, s16le
    frames = list(speech_frames(7, pcm, 24_000))
    assert len(frames) == 20 and all(len(f) == 5 + 4800 for f in frames)
    assert all(f[0] == SPEECH and int.from_bytes(f[1:5], "big") == 7 for f in frames)
    assert b"".join(f[5:] for f in frames) == pcm
    assert [len(f) - 5 for f in speech_frames(1, pcm[:5000], 24_000)] == [4800, 200]


def test_assets_are_versioned_by_their_files_and_gzipped_once(tmp_path):
    (tmp_path / "js").mkdir()
    (tmp_path / "index.html").write_text('<head><script type="module" src="/studio/static/js/main.js"></script></head>')
    (tmp_path / "js" / "main.js").write_text("import './a.js';\n" * 50)
    (tmp_path / "js" / "a.js").write_text("export const a = 1;")
    (tmp_path / "js" / "mic-worklet.js").write_text("")
    assets = Assets(tmp_path)
    version = assets.version()
    assert assets.split(f"{version}/js/main.js") == (version, "js/main.js")
    assert assets.split("js/main.js") == (None, "js/main.js")
    data, gz, ctype = assets.file("js/main.js")
    assert gzip.decompress(gz) == data and len(gz) < len(data) and ctype == "text/javascript; charset=utf-8"
    assert assets.file("../outside.txt") is None and assets.file("js/none.js") is None

    page = assets.page({"items": [{"data": {"text": "</script><b>"}}]})
    assert f'src="/studio/static/{version}/js/main.js"' in page
    assert f'<link rel="modulepreload" href="/studio/static/{version}/js/a.js">' in page and "mic-worklet" not in page
    assert "</script><b>" not in page and json.loads(re.search(r'id="boot">(.*?)</script>', page).group(1)) == {
        "items": [{"data": {"text": "</script><b>"}}]}

    (tmp_path / "js" / "a.js").write_text("export const a = 2;")      # a deploy: a new version, and the new file
    assets._checked = -1e9
    assert assets.version() != version and assets.file("js/a.js")[0] == b"export const a = 2;"


@pytest.mark.parametrize("header, ok", [("gzip, deflate, br", True), ("br;q=1.0, gzip;q=0.5", True), ("", False),
                                        ("gzip;q=0", False), ("deflate", False), ("x-gzip", False)])
def test_gzip_only_where_the_browser_takes_it(header, ok):
    assert accepts_gzip(header) is ok
