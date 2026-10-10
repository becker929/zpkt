"""hands doctor: the rig checks, on the throwaway rig from conftest, Live faked."""
from __future__ import annotations

import json

from planted import planted_set

from hands import doctor as D
from hands.live import session
from hands.live.transport import MockTransport


def _by_name(checks):
    return {c.name: c for c in checks}


def test_a_rig_without_kits_fails_and_says_where_it_looked(rig, tmp_path):
    env = {"ZPKT_RIG_CONFIG": str(tmp_path / "none.toml"), "ZPKT_SETS_DIR": str(rig.sets_dir)}
    checks = _by_name(D.run(env=env))
    assert checks["config"].status == D.OK and "ZPKT_SETS_DIR" in checks["config"].detail
    assert checks["sets_dir"].status == D.OK
    assert checks["kits"].status == D.FAIL and str(rig.data_dir / "kits") in checks["kits"].detail


def test_no_config_at_all_is_a_warning(rig, tmp_path):
    assert D.run(env={"ZPKT_RIG_CONFIG": str(tmp_path / "none.toml")})[0].status == D.WARN


def test_each_kit_needs_its_set_under_our_prefix(rig):
    kits = rig.data_dir / "kits"
    kits.mkdir()
    for kit, set_name in (("good", "test_kit_good"), ("gone", "test_kit_gone"), ("theirs", "other_kit")):
        (kits / f"{kit}.json").write_text(json.dumps({"kit": kit, "set": set_name}))
    planted_set(rig.set_path("test_kit_good"))
    planted_set(rig.set_path("other_kit"))
    checks = _by_name(D.run(env={}))
    assert checks["kit good"].status == D.OK
    assert checks["kit gone"].status == D.FAIL and "not in" in checks["kit gone"].detail
    assert checks["kit theirs"].status == D.FAIL and "prefixes" in checks["kit theirs"].detail


def test_live_answering_and_the_front_set(rig, monkeypatch):
    monkeypatch.setattr(session, "_answers", lambda client: True)
    monkeypatch.setattr(session, "_front", lambda: "someone_elses_song")
    checks = _by_name(D.run(MockTransport(), env={}))
    assert checks["live answers"].status == D.OK
    assert checks["front set"].status == D.WARN and "not ours" in checks["front set"].detail
    monkeypatch.setattr(session, "_answers", lambda client: False)
    checks = _by_name(D.run(MockTransport(), env={}))
    assert checks["live answers"].status == D.FAIL and "front set" not in checks
