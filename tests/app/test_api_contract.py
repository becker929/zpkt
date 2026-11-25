"""The API's wire shapes match lib/contracts/app-api.schema.json: real replies validate, and the schema's names are
the code's."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from zpkt.app.jobs import API_CALLERS

SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "lib" / "contracts" / "app-api.schema.json").read_text())


def check(name: str, instance) -> None:
    jsonschema.validate(instance, {"$ref": f"#/$defs/{name}", "$defs": SCHEMA["$defs"]})


def test_the_schema_is_a_schema():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


def test_who_in_the_schema_is_who_the_api_allows():
    assert tuple(SCHEMA["$defs"]["who"]["enum"]) == API_CALLERS


def test_health_commands_and_a_run_validate(api):
    check("health", api.get("/health", token=None)[1])
    check("commands", api.get("/commands")[1])
    ok = api.run("result = song.tempo")[1]
    check("run_reply", ok)
    check("run_reply", api.run("song.nonsense_attribute")[1])


def test_the_errors_validate(api):
    for reply in (
        api.run("1", who="agent")[1],  # 403
        api.run("1", who="you")[1],  # 400
        api.post("/live/run", {}, token="x")[1],  # 401
        api.post("/command", {"kind": "nope"})[1],  # 404
    ):
        check("error", reply)


def test_the_requests_the_client_sends_validate(api):
    from zpkt.app.client import AppClient

    sent = []
    c = AppClient("booth", url=api.url, token=api.token)
    original = c._send
    c._send = lambda method, path, body, auth=True: sent.append(body) or original(method, path, body, auth)  # type: ignore[method-assign]
    c.submit("live.run", {"code": "1"}, group="g")
    c.submit("live.run", {"code": "1"}, approval="option:1")
    bodies = [b for b in sent if b]
    assert bodies and all(not check("request", b) for b in bodies)
    assert bodies[0]["who"] == "booth" and bodies[0]["group"] == "g"


@pytest.mark.parametrize("bad", [{"who": "you"}, {"who": "cli", "args": []}])
def test_a_request_the_schema_rejects_is_one_the_api_rejects(api, bad):
    with pytest.raises(jsonschema.ValidationError):
        check("request", {"kind": "live.run", **bad})
    assert api.post("/command", {"kind": "live.run", **bad})[0] == 400
