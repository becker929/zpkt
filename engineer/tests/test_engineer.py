"""engineer: the loop calls ears with a flag ears has."""
from __future__ import annotations

import json
import stat

from engineer.loop import Loop
from taste.models import Verdict


def _script(path, body: str) -> str:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_loop_cycle_passes_ears_json_to_the_judge(tmp_path) -> None:
    calls = tmp_path / "calls.log"
    render = tmp_path / "render.wav"
    hands = _script(tmp_path / "hands", f'echo "hands $@" >> {calls}\n'
                    f'case "$1" in record) touch "$5";; esac\n')
    # A stand-in ears that only accepts the flag the real ears has.
    ears = _script(tmp_path / "ears", f'echo "ears $@" >> {calls}\n'
                   '[ "$3" = "--json" ] || { echo "unknown flag $3" >&2; exit 2; }\n'
                   'echo \'{"clip_id": "x", "audio_path": "r.wav"}\'\n')

    seen = {}

    class Judge:
        def judge(self, profile_json: str) -> Verdict:
            seen["profile"] = json.loads(profile_json)
            return Verdict(clip_id="x", score=3, rationale="stub")

    loop = Loop(hands_bin=hands, ears_bin=ears, store=object(), judge=Judge())
    verdict = loop.run_cycle(str(tmp_path / "config.json"), beats=8)

    assert verdict.score == 3
    assert seen["profile"]["clip_id"] == "x"
    log = calls.read_text()
    assert "hands execute" in log and "hands record" in log and "--json" in log
