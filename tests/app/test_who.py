"""Who a caller of the API is: the token it sends says so, never the request."""

from __future__ import annotations

import stat

import pytest

from zpkt.app import token
from zpkt.app.adapters.api import parse_request
from zpkt.app.bus import BadRequest, Refused
from zpkt.app.client import AppClient

TEMPO = {"bpm": 104.0}


@pytest.fixture()
def app_env(api, monkeypatch):
    monkeypatch.setenv("ZPKT_APP_URL", api.url)
    monkeypatch.delenv("ZPKT_LIVE_VIA", raising=False)
    monkeypatch.delenv("ZPKT_AGENT", raising=False)
    monkeypatch.delenv("ZPKT_OPTION", raising=False)
    return api


# ---- the token says who ----------------------------------------------------------------------------------------------


def test_each_caller_has_its_own_token_file_mode_0600(api):
    files = {who: token.token_path(api.config_dir, who) for who in token.CALLERS}
    assert {f.name for f in files.values()} == {"app-token", "app-token-agent", "app-token-booth", "app-token-demo"}
    assert files["cli"].name == "app-token"  # the first file keeps its name
    for who, f in files.items():
        assert stat.S_IMODE(f.stat().st_mode) == 0o600, who
        assert f.read_text().strip() == api.tokens[who]
    assert len(set(api.tokens.values())) == len(token.CALLERS)
    assert stat.S_IMODE(api.config_dir.stat().st_mode) == 0o700


def test_there_is_no_token_for_you_the_minilab_or_sys(tmp_path):
    for who in ("you", "minilab", "sys"):
        with pytest.raises(ValueError, match="no token"):
            token.token_path(tmp_path, who)
    assert set(token.ensure_tokens(tmp_path)) == {"agent", "booth", "demo", "cli"}


@pytest.mark.parametrize("who", ["cli", "booth", "demo"])
def test_a_call_is_stamped_by_its_token_when_the_request_says_nothing(api, rig, who):
    code, _ = api.post("/live/tempo", {"args": TEMPO}, token=api.tokens[who])
    assert code == 200
    assert rig.desk.bus.log[-1]["who"] == who


@pytest.mark.parametrize(("holder", "claims"), [("cli", "booth"), ("cli", "demo"), ("agent", "cli"), ("booth", "demo")])
def test_a_token_cannot_ask_as_someone_else(api, rig, holder, claims):
    before = len(rig.desk.bus.log)
    code, body = api.post("/live/tempo", {"who": claims, "args": TEMPO}, token=api.tokens[holder])
    assert code == 403 and f"this token is {holder}'s" in body["error"]
    assert len(rig.desk.bus.log) == before and rig.live.song.tempo != TEMPO["bpm"]  # nothing reached the bus


@pytest.mark.parametrize("who", ["you", "minilab", "sys"])
def test_you_and_the_minilab_are_never_accepted_from_the_api(api, rig, who):
    for holder in token.CALLERS:
        code, body = api.post("/command", {"kind": "mix.set", "who": who, "args": {}}, token=api.tokens[holder])
        assert code == 400 and "'who' is one of" in body["error"], holder
    assert all(entry["who"] != who for entry in rig.desk.bus.log)


def test_the_agents_token_is_held_to_the_agent_rule_whatever_the_request_says(api, rig):
    code, body = api.post("/live/tempo", {"args": TEMPO}, token=api.tokens["agent"])
    assert code == 403 and "cannot change Live" in body["error"]
    code, body = api.post("/live/tempo", {"args": TEMPO, "approval": "user"}, token=api.tokens["agent"])
    assert code == 400 and "cannot say the user approved" in body["error"]
    assert rig.live.song.tempo != TEMPO["bpm"]


def test_a_token_that_is_not_ours_or_not_a_bearer_is_a_401(api):
    assert api.post("/live/tempo", {"args": TEMPO}, token="not-a-token")[0] == 401
    code, _ = api.call("POST", "/api/v1/live/tempo", {"args": TEMPO}, token=None, headers={"Authorization": api.token})
    assert code == 401


def test_parsing_with_a_token_stamps_the_tokens_name():
    assert parse_request({"kind": "x"}, who="booth").who == "booth"
    assert parse_request({"kind": "x", "who": "booth"}, who="booth").who == "booth"
    with pytest.raises(Refused, match="cannot ask as demo"):
        parse_request({"kind": "x", "who": "demo"}, who="booth")
    with pytest.raises(BadRequest):
        parse_request({"kind": "x", "who": "you"}, who="booth")


# ---- the client sends its own token ----------------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["cli", "booth", "demo", "agent"])
def test_the_client_reads_the_token_file_of_who_it_is(app_env, rig, who):
    c = AppClient(who)
    assert c.token() == app_env.tokens[who]
    assert c.submit("live.read", {"code": "result = 1"})[0] == 200
    assert rig.desk.bus.log[-1]["who"] == who


def test_a_client_with_another_callers_token_is_refused_not_believed(app_env, rig):
    c = AppClient("booth", token=app_env.tokens["cli"])
    code, body = c.submit("live.set_tempo", TEMPO)
    assert code == 403 and "this token is cli's" in body["error"]
