"""The lab's server side: the parameter plan, the params file it wrote, reading a Live set, and the routes."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from harness.studio import lab_params
from harness.studio.lab_audio import arrangement

STATIC = Path(lab_params.__file__).parent / "static" / "lab"
STAGES = {"collage", "arrange", "kick", "mix"}


def test_the_plan_is_100_params_with_unique_ids_on_the_four_stages():
    plan = lab_params.plan()
    assert len(plan) == 100
    assert len({p.id for p in plan}) == 100
    assert {p.stage for p in plan} == STAGES
    for p in plan:
        assert p.scale in {"lin", "log", "toggle", "enum"}, p.id
        assert p.scale != "enum" or p.options, p.id
        assert p.scale != "log" or 0 < p.min < p.max, p.id
        assert p.at is not None or p.set is not None, f"{p.id}: neither read from the set nor given"
        if p.tried:
            assert p.min <= min(p.tried) and max(p.tried) <= p.max, f"{p.id}: tried {p.tried} outside the range"


def test_the_params_file_matches_the_plan_and_every_set_value_is_in_range():
    data = json.loads((STATIC / "data" / "params.json").read_text())
    rows = data["params"]
    assert [r["id"] for r in rows] == [p.id for p in lab_params.plan()]
    for r in rows:
        if r["scale"] in ("lin", "log"):
            assert r["min"] - 1e-6 <= r["set"] <= r["max"] + 1e-6, f"{r['id']}: set {r['set']} outside [{r['min']}, {r['max']}]"
        assert r["origin"] in ("set", "arrangement")
        assert (r["live"] is None) == (r["origin"] == "arrangement"), r["id"]


def _set(tmp_path: Path) -> Path:
    """A tiny .als: a group with an EQ Eight and a plugin, a track in it with a clip, and the main track."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Ableton><LiveSet>
 <Tracks>
  <GroupTrack Id="5"><Name><EffectiveName Value="kick group"/></Name><TrackGroupId Value="-1"/>
   <DeviceChain><Mixer><Volume><Manual Value="0.5"/></Volume><Speaker><Manual Value="true"/></Speaker></Mixer>
    <DeviceChain><Devices>
     <Eq8><On><Manual Value="true"/></On><Bands.0><ParameterA><Gain><Manual Value="-14.75"/></Gain></ParameterA></Bands.0></Eq8>
     <PluginDevice><On><Manual Value="true"/></On><PluginDesc><VstPluginInfo><PlugName Value="Dist COLDFIRE"/></VstPluginInfo></PluginDesc>
      <ParameterList><PluginFloatParameter><ParameterName Value="Distortion A Drive"/><ParameterValue><Manual Value="0.1235"/></ParameterValue></PluginFloatParameter></ParameterList>
     </PluginDevice>
    </Devices></DeviceChain></DeviceChain>
  </GroupTrack>
  <AudioTrack Id="6"><Name><EffectiveName Value="rumble"/></Name><TrackGroupId Value="5"/>
   <DeviceChain><Mixer><Speaker><Manual Value="true"/></Speaker></Mixer>
    <MainSequencer><Sample><ArrangerAutomation><Events>
     <AudioClip><CurrentStart Value="16"/><CurrentEnd Value="32"/><IsWarped Value="true"/>
      <Loop><LoopStart Value="4"/><LoopEnd Value="8"/><LoopOn Value="false"/></Loop>
      <WarpMarkers><WarpMarker SecTime="15" BeatTime="0"/><WarpMarker SecTime="16" BeatTime="2"/></WarpMarkers>
      <SampleRef><FileRef><Path Value="/x/rumble.aif"/></FileRef></SampleRef></AudioClip>
     <AudioClip><CurrentStart Value="40"/><CurrentEnd Value="48"/><IsWarped Value="false"/>
      <Loop><LoopStart Value="33.5"/><LoopEnd Value="40"/><LoopOn Value="false"/></Loop>
      <SampleRef><FileRef><Path Value="/x/game.wav"/></FileRef></SampleRef></AudioClip>
    </Events></ArrangerAutomation></Sample></MainSequencer>
    <DeviceChain><Devices/></DeviceChain></DeviceChain>
  </AudioTrack>
  <AudioTrack Id="7"><Name><EffectiveName Value="a muted reference"/></Name><TrackGroupId Value="-1"/>
   <DeviceChain><Mixer><Speaker><Manual Value="false"/></Speaker></Mixer><DeviceChain><Devices/></DeviceChain></DeviceChain>
  </AudioTrack>
 </Tracks>
 <MainTrack><DeviceChain><DeviceChain><Devices/></DeviceChain></DeviceChain></MainTrack>
 <Tempo><Manual Value="160"/></Tempo>
</LiveSet></Ableton>"""
    path = tmp_path / "tiny.als"
    path.write_bytes(gzip.compress(xml.encode()))
    return path


def test_values_are_read_from_the_set_in_lives_units(tmp_path):
    tr = lab_params.tracks(_set(tmp_path))
    assert float(lab_params.read(tr, ("kick group", "Eq8:0", "Bands.0/ParameterA/Gain"))) == -14.75
    raw = lab_params.read(tr, ("kick group", "plugin:Dist COLDFIRE", "Distortion A Drive"))
    assert lab_params.convert(raw, "pct") == pytest.approx(12.35)
    assert lab_params.convert(lab_params.read(tr, ("kick group", "Mixer", "Volume")), "lin2db") == pytest.approx(-6.02, abs=0.01)
    assert lab_params.read(tr, ("kick group", "plugin:Decapitator", "Drive")) is None


def test_the_arrangement_skips_muted_tracks_and_counts_in_bars(tmp_path):
    tempo, tracks, clips = arrangement(_set(tmp_path))
    assert tempo == 160
    assert [t["name"] for t in tracks] == ["kick group", "rumble", "a muted reference"]
    assert tracks[1]["group"] == "kick group" and tracks[2]["muted"]
    assert [(c.track, c.start, c.end) for c in clips] == [("rumble", 16.0, 32.0), ("rumble", 40.0, 48.0)]
    assert tracks[1]["clips"] == [[4.0, 8.0, "/x/rumble.aif"], [10.0, 12.0, "/x/game.wav"]]


def test_where_a_clip_plays_in_its_file_follows_the_warp_markers(tmp_path):
    _, _, clips = arrangement(_set(tmp_path))
    warped, plain = clips
    assert warped.file_s == (17.0, 25.0)     # beats 4..20 at 2 beats a second from 15 s (the last segment extended)
    assert plain.file_s == (33.5, 36.5)      # seconds as they are; 8 beats at 160 BPM is 3 s


async def test_the_routes_serve_the_lab_and_its_audio_and_nothing_else(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).parent / "ui"))
    from lab_server import app
    (tmp_path / "manifest.json").write_text("{}")
    (tmp_path / "a.mp3").write_bytes(b"ID3")
    client = TestClient(TestServer(app(tmp_path)))
    await client.start_server()
    try:
        r = await client.get("/studio/lab", allow_redirects=False)
        assert r.status == 302 and r.headers["Location"] == "/studio/lab/"
        r = await client.get("/studio/lab/")
        assert r.status == 200 and "HW002 lab" in await r.text()
        assert (await client.get("/studio/lab/data/params.json")).status == 200
        r = await client.get("/studio/lab/audio/a.mp3")
        assert r.status == 200 and "immutable" in r.headers["Cache-Control"]
        assert (await client.get("/studio/lab/audio/manifest.json")).headers["Cache-Control"] == "no-cache"
        for bad in ("/studio/lab/audio/..%2Fmanifest.json", "/studio/lab/..%2F..%2Froutes.py", "/studio/lab/nope.js"):
            assert (await client.get(bad)).status == 404, bad
    finally:
        await client.close()
