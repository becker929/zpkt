"""The song's key (key.get, key.set) and a Mixer surface for a song of its own (surface.mixer), from the persona
walkthrough of 27 November 2026: "no key control on the Song tab" and "No mixer in the app, only Ask"."""

from __future__ import annotations


def test_the_key_is_read_and_set_in_live(rig):
    code, got = rig.command("key.get")
    assert code == 200 and got["note"] == "C" and got["scale"] == "Major" and "Minor" in got["scales"]
    code, got = rig.command("key.set", {"root": 9, "scale": "Minor"})
    assert code == 200 and got["note"] == "A"
    song = rig.live.song
    assert (song.root_note, song.scale_name, song.scale_mode) == (9, "Minor", True)
    assert rig.command("key.set", {"root": "A", "scale": "Minor"})[0] == 200
    assert rig.command("key.set", {"root": 12, "scale": "Minor"})[0] == 400
    assert rig.command("key.set", {"root": 9, "scale": "Blues-ish"})[0] == 400


def test_the_mixer_is_every_tracks_volume_and_mains(rig):
    code, got = rig.command("surface.mixer")
    assert code == 200 and got["ok"] and got["title"] == "Mixer", got
    tracks = [t.name for t in rig.live.song.tracks] + [t.name for t in rig.live.song.return_tracks]
    want = [n for n in tracks if not n.casefold().startswith("mon ")][:23]
    import json

    drawn = json.dumps(got["minilab"])
    assert "Main/volume" in drawn and all(f"{n}/volume" in drawn for n in want), drawn[:400]
