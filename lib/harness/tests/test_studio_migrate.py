"""`harness studio-music-mp3`: old FLAC music becomes MP3, once, against a store of its own."""

import shutil
import sys

import numpy as np
import pytest
import soundfile as sf

from harness import cli
from harness.config import Config
from harness.studio.migrate import music_to_mp3
from harness.studio.model import Kind, Message
from harness.studio.store import Store

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


def flac(seconds=0.5, rate=44_100) -> bytes:
    import io
    x = 0.3 * np.sin(2 * np.pi * 220 * np.arange(int(seconds * rate)) / rate)
    buf = io.BytesIO()
    sf.write(buf, np.stack([x, x], axis=1), rate, format="FLAC", subtype="PCM_24")
    return buf.getvalue()


def a_store_with_old_music(root):
    store = Store(root)
    conv = store.conversation()
    old = store.put_media(flac(), "flac")
    gone = store.put_media(b"not kept", "flac")
    store.media_file(gone.url.rsplit("/", 1)[1]).unlink()
    new = store.put_media(b"ID3 an mp3 already", "mp3")
    seqs = {}
    for name, ref in (("old", old), ("gone", gone), ("new", new)):
        seqs[name] = store.add(Message(Kind.MUSIC, {"title": name, "audio": ref.wire(), "duration": 0.5, "plays": 2},
                                       conversation=conv.id)).seq
    store.add(Message(Kind.AGENT, {"text": "a flac", "audio": old.wire()}, conversation=conv.id))   # not music
    return store, seqs, old


async def test_flac_music_becomes_mp3_once_and_the_flac_is_kept(tmp_path):
    store, seqs, old = a_store_with_old_music(tmp_path)
    assert [(c.seq, c.status) for c in await music_to_mp3(store, dry_run=True)] == [
        (seqs["old"], "would convert"), (seqs["gone"], "missing")]
    assert store.get(seqs["old"]).data["audio"] == old.wire()          # a dry run changes nothing

    done = await music_to_mp3(store)
    assert [(c.seq, c.status) for c in done] == [(seqs["old"], "converted"), (seqs["gone"], "missing")]
    msg = store.get(seqs["old"])
    mp3 = store.media_file(msg.data["audio"]["url"].rsplit("/", 1)[1])
    assert msg.data["audio"]["type"] == "audio/mpeg" and mp3 is not None
    assert mp3.read_bytes()[:3] == b"ID3" or mp3.read_bytes()[0] == 0xFF
    assert msg.data["original"] == old.wire() and msg.data["plays"] == 2 and msg.rev == 1
    assert store.media_file(old.url.rsplit("/", 1)[1]) is not None    # the FLAC stays
    assert store.get(seqs["new"]).rev == 0

    again = await music_to_mp3(store)
    assert [(c.seq, c.status) for c in again] == [(seqs["gone"], "missing")]
    assert store.get(seqs["old"]).rev == 1
    store.close()


def test_the_command_converts_the_store_it_is_pointed_at(tmp_path, monkeypatch, capsys):
    store, seqs, _ = a_store_with_old_music(tmp_path / "studio")
    store.close()
    monkeypatch.setattr(sys, "argv", ["harness", "studio-music-mp3"])
    monkeypatch.setattr(cli, "Config", lambda: Config(studio_dir=tmp_path / "studio", jobs_dir=tmp_path / "jobs",
                                                      skrng_dir=tmp_path / "skrng"))
    cli.main()
    out = capsys.readouterr().out
    assert f"#{seqs['old']}  converted" in out and "1 converted of 2" in out
    reopened = Store(tmp_path / "studio")
    assert reopened.get(seqs["old"]).data["audio"]["type"] == "audio/mpeg"
    reopened.close()
