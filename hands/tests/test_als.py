"""hands.als on the BSD fixture set, with devices planted the way Live 12 writes them."""
from __future__ import annotations

import copy
import gzip
import xml.etree.ElementTree as ET

import pytest
from planted import DECAPITATOR, FIXTURE, TRACK, planted_set, planted_tree, xml_text
from typer.testing import CliRunner

from hands import als
from hands.cli import app

UTIL = ("StereoGain", 0)
DECAP = ("plugin", "Decapitator")


def test_load_and_save_round_trip_byte_for_byte(tmp_path):
    out = als.save(als.load(FIXTURE), tmp_path / "copy.als")
    assert gzip.open(out).read() == gzip.open(FIXTURE).read()
    assert not (tmp_path / "copy.als.tmp").exists()
    with pytest.raises(FileExistsError):
        als.save(als.load(FIXTURE), out)


def test_xml_hash_ignores_gzip_and_sees_changes(tmp_path):
    again = tmp_path / "again.als"
    again.write_bytes(gzip.compress(gzip.open(FIXTURE).read(), compresslevel=1, mtime=12345))
    assert again.read_bytes() != FIXTURE.read_bytes()
    assert als.xml_hash(again) == als.xml_hash(FIXTURE)
    tree = als.load(FIXTURE)
    als.set_speaker(tree, TRACK, False)
    assert als.xml_hash(als.save(tree, tmp_path / "muted.als")) != als.xml_hash(FIXTURE)


def test_tracks_and_devices():
    tree = planted_tree()
    assert [als.track_name(t) for t in als.all_tracks(tree)] == ["1-Audio", "Main", "Master"]
    assert [d.tag for d in als.devices(als.find_track(tree, TRACK))] == ["StereoGain", "PluginDevice", "Eq8"]
    with pytest.raises(LookupError, match="0 tracks"):
        als.find_track(tree, "nope")
    twin = copy.deepcopy(als.find_track(tree, TRACK))
    tree.getroot().find("LiveSet/Tracks").append(twin)
    with pytest.raises(LookupError, match="2 tracks"):
        als.find_track(tree, TRACK)


def test_knob_values_and_ranges():
    tree = planted_tree()
    assert als.current_value(tree, TRACK, "Mixer", "Volume") == 1.0
    assert als.current_value(tree, TRACK, "Mixer", "Speaker") is True
    assert als.current_value(tree, TRACK, UTIL, "Gain") == pytest.approx(0.4084238708)
    assert als.current_value(tree, TRACK, "StereoGain", "BassMono") is False   # bare tag: the last one
    assert als.current_value(tree, TRACK, DECAP, "Drive") == pytest.approx(0.27)
    assert als.current_value(tree, TRACK, ("Eq8", 0), "Bands.0/ParameterA/Freq") == pytest.approx(30.9539299)
    assert als.param_range(tree, TRACK, UTIL, "StereoWidth") == (0.0, 4.0)
    assert als.param_range(tree, TRACK, DECAP, "Mix") == (0.0, 1.0)
    assert als.param_range(tree, TRACK, "Mixer", "Speaker") is None
    with pytest.raises(KeyError, match="parameters named 'Tone'"):
        als.current_value(tree, TRACK, DECAP, "Tone")
    with pytest.raises(KeyError, match="no automatable 'Width'"):
        als.current_value(tree, TRACK, UTIL, "Width")


def test_set_manual_checks_type_range_and_automation():
    tree = planted_tree()
    als.set_manual(tree, TRACK, UTIL, "StereoWidth", 1.5)
    als.set_manual(tree, TRACK, UTIL, "ChannelMode", 2)
    assert als.current_value(tree, TRACK, UTIL, "StereoWidth") == 1.5
    assert als.knob_param(tree, TRACK, UTIL, "ChannelMode").find("Manual").get("Value") == "2"
    with pytest.raises(ValueError, match="outside"):
        als.set_manual(tree, TRACK, UTIL, "StereoWidth", 4.5)
    with pytest.raises(TypeError, match="True/False"):
        als.set_manual(tree, TRACK, UTIL, "BassMono", 1)
    tr, dev, path = als.resolve(tree, TRACK, DECAP, "Drive")
    als.set_steps(tree, tr, dev, path, [(0, 0.2), (8, 0.4)])
    with pytest.raises(ValueError, match="automated"):
        als.set_manual(tree, TRACK, DECAP, "Drive", 0.5)


def test_speaker_and_rename():
    tree = planted_tree()
    als.set_speaker(tree, TRACK, False)
    assert als.current_value(tree, TRACK, "Mixer", "Speaker") is False
    als.rename_track(tree, TRACK, "S01 chord")
    tr = als.find_track(tree, "S01 chord")
    assert tr.find("Name/UserName").get("Value") == "S01 chord"
    with pytest.raises(ValueError, match="already named"):
        als.rename_track(tree, "S01 chord", "Main")


def test_set_steps_writes_a_step_envelope_live_can_load(tmp_path):
    tree = planted_tree()
    tr, dev, path = als.resolve(tree, TRACK, DECAP, "Drive")
    als.set_steps(tree, tr, dev, path, [(0, 0.2), (40, 0.4), (72, 0.4), (104, 0.8)])
    tr, eq, _ = als.resolve(tree, TRACK, ("Eq8", 0), "Bands.0/ParameterA/IsOn")
    als.set_steps(tree, tr, eq, "Bands.0/ParameterA/IsOn", [(0, True), (40, False)])
    out = als.save(tree, tmp_path / "steps.als")
    envs = als.envelopes(als.load(out))
    drive = [(e.tag, e.get("Time"), e.get("Value")) for e in envs["1-Audio > PluginDevice > ParameterValue"][2]]
    assert drive == [("FloatEvent", "-63072000", "0.2"), ("FloatEvent", "0", "0.2"),
                     ("FloatEvent", "40", "0.2"), ("FloatEvent", "40", "0.4"), ("FloatEvent", "72", "0.4"),
                     ("FloatEvent", "104", "0.4"), ("FloatEvent", "104", "0.8")]
    ison = [(e.tag, e.get("Time"), e.get("Value")) for e in envs["1-Audio > Eq8 > IsOn"][2]]
    assert ison[0] == ("BoolEvent", "-63072000", "true") and ison[-1] == ("BoolEvent", "40", "false")
    report = als.check(out, against=FIXTURE)
    assert report.problems == [], str(report)
    assert any("+ envelope 1-Audio > PluginDevice > ParameterValue" in line for line in report.lines)
    # rewriting replaces the events, it does not add a second envelope
    tree = als.load(out)
    tr, dev, path = als.resolve(tree, TRACK, DECAP, "Drive")
    als.set_steps(tree, tr, dev, path, [(0, 0.5)])
    assert [e.get("Value") for e in als.envelopes(tree)["1-Audio > PluginDevice > ParameterValue"][2]] == ["0.5", "0.5"]


def test_set_steps_refuses_bad_input():
    tree = planted_tree()
    tr, dev, path = als.resolve(tree, TRACK, UTIL, "StereoWidth")
    with pytest.raises(ValueError, match="strictly increasing"):
        als.set_steps(tree, tr, dev, path, [(8, 1.0), (8, 2.0)])
    with pytest.raises(ValueError, match="outside"):
        als.set_steps(tree, tr, dev, path, [(0, 1.0), (8, 9.0)])
    main = als.find_track(tree, "Main")
    with pytest.raises(ValueError, match="not in track"):
        als.set_steps(tree, main, dev, path, [(0, 1.0)])
    assert len(als.envelopes(tree)) == 2   # only the fixture's own two on Main


def test_add_device_from_donor_renumbers_its_ids(tmp_path):
    tree = als.load(FIXTURE)
    donor = ET.fromstring(DECAPITATOR)          # ids 22110-22115, as if from another set
    dev = als.add_device_from_donor(tree, als.find_track(tree, TRACK), donor)
    ids = sorted(int(e.get("Id")) for e in als.pointee_elements(dev))
    assert ids == list(range(22031, 22037))      # from the fixture's NextPointeeId on
    assert tree.getroot().find("LiveSet/NextPointeeId").get("Value") == "22037"
    assert dev.get("Id") == "0"
    out = als.save(tree, tmp_path / "donor.als")
    assert als.check(out).problems == []
    assert als.current_value(als.load(out), TRACK, DECAP, "Drive") == pytest.approx(0.27)


def test_donor_references_and_routings():
    tree = als.load(FIXTURE)
    outside = ET.fromstring('<Reverb Id="0"><Envelope><PointeeId Value="5" /></Envelope></Reverb>')
    with pytest.raises(ValueError, match="outside itself"):
        als.add_device_from_donor(tree, als.find_track(tree, TRACK), outside)
    sidechain = ET.fromstring('<Compressor2 Id="0"><SideChain><Target Value="AudioIn/Track.7/PostFxOut" />'
                              '</SideChain></Compressor2>')
    with pytest.warns(UserWarning, match="donor set"):
        als.add_device_from_donor(tree, als.find_track(tree, TRACK), sidechain)


def test_check_finds_what_would_break_loading(tmp_path):
    text = xml_text(planted_set(tmp_path / "ok.als"))
    broken = text.replace('<Pointee Id="22117" />', '<Pointee Id="22101" />')       # a duplicate id
    broken = broken.replace('<NextPointeeId Value="22200" />', '<NextPointeeId Value="22120" />')
    path = tmp_path / "broken.als"
    path.write_bytes(gzip.compress(broken.encode()))
    problems = als.check(path).problems
    assert any("duplicated pointee ids" in p for p in problems)
    assert any("NextPointeeId 22120" in p for p in problems)


def test_list_params_and_cli(tmp_path):
    path = planted_set(tmp_path / "planted.als")
    lines = als.list_params(path, TRACK, "StereoGain")
    assert lines[0].split()[:2] == ["On", "Bool"] and any(line.startswith("Gain ") for line in lines)
    out = CliRunner().invoke(app, ["als", "check", str(path), "--against", str(FIXTURE)])
    assert out.exit_code == 0 and out.stdout.rstrip().endswith("OK")
    out = CliRunner().invoke(app, ["als", "params", str(path), TRACK, "Eq8"])
    assert out.exit_code == 0 and out.stdout.split()[:2] == ["On", "Bool"]
    assert "Bands" not in out.stdout   # band parameters sit one level down
