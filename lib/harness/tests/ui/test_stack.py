"""The whole stack, end to end: the page in Chromium, the real server, the real speech models (Kokoro, Parakeet), and
`hands plan` making an A/B. Claude is scripted (it runs the same command Claude would), and the A/B's renders are
stand-in tones (Live is not touched).

    STUDIO_STACK=1 uv run --extra dev pytest tests/ui/test_stack.py          # ~1 min; models load once
    STUDIO_CLAUDE=1 ... -k real_claude                                         # one typed turn with real Claude

They need the speech models (`uv sync --project lib/voice --extra engines`), Playwright's Chromium, a probe kit for
the plan test (c8x4, ~/_agent_scratch/probepack/kits/), and for the last one a logged-in Claude Code.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from aiohttp.test_utils import TestServer

from conftest import CAPTURE, MUTE, PHONE
from harness.config import ZPKT, Config, voice_command
from harness.studio import Studio
from harness.studio.agent import TextDelta, TextDone, ToolDone, ToolStart, TurnDone
from harness.studio.shots import Frame
from harness.studio.speech import VoiceWorker
from harness.studio.timing import report
from harness.web import App

pytestmark = [pytest.mark.ui, pytest.mark.skipif(os.environ.get("STUDIO_STACK") != "1" and
                                                 os.environ.get("STUDIO_CLAUDE") != "1",
                                                 reason="STUDIO_STACK=1 runs the real speech models and the page")]

PW = "correct horse battery"
UV = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")
DRIVE = "rumble|plugin:Decapitator|Drive"


class ScriptedClaude:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.script = lambda prompt: [TurnDone("ok", True, 0.0, "s1")]
        self.session_id = None

    async def turn(self, prompt):
        self.prompts.append(prompt)
        for step in self.script(prompt):
            if callable(step):
                await step()
            else:
                yield step

    async def interrupt(self):
        pass

    async def close(self):
        pass


class StillScreen:
    async def grab(self):
        return Frame(np.zeros((360, 640, 3), np.uint8), asyncio.get_running_loop().time())


async def quiet(_prompt):
    return ""


def kokoro_wav(text: str, out: Path) -> bytes:
    """What Anthony says, spoken by Kokoro, with 2 s of silence after it (the page's stand-in mic loops the file)."""
    import soundfile as sf
    subprocess.run([UV, "run", "--project", str(ZPKT / "lib" / "voice"), "--extra", "engines", "voice", "say", text,
                    "-o", str(out), "--voice", "am_michael"], check=True, capture_output=True, timeout=300)
    x, sr = sf.read(out, dtype="float32")
    sf.write(out, np.concatenate([np.zeros(sr // 2, np.float32), x, np.zeros(2 * sr, np.float32)]), sr,
             subtype="PCM_16")
    return out.read_bytes()


@pytest.fixture
async def stack(tmp_path, monkeypatch):
    monkeypatch.setenv("HANDS_PLANS", str(tmp_path / "plans"))
    cfg = Config(jobs_dir=tmp_path / "jobs", workdir=ZPKT, skrng_dir=tmp_path / "skrng",
                 studio_dir=tmp_path / "studio", steps_port=0)
    claude = None if os.environ.get("STUDIO_CLAUDE") == "1" else ScriptedClaude()
    studio = Studio(cfg, worker=VoiceWorker(voice_command()), agent=claude, capture=StillScreen(), summarize=quiet)
    server = TestServer(App(cfg, None, cfg.skrng_dir, secure_cookie=False, studio=studio).build())
    await server.start_server()
    assert await studio.worker.wait_ready(300), "the voice worker (Kokoro, Parakeet) did not start"
    assert studio.worker.info["tts"].startswith("kokoro") and studio.worker.info["stt"].startswith("parakeet")
    yield server, studio, claude, tmp_path
    await server.close()


async def phone(chromium, server, studio, mic: bytes | None = None):
    context = await chromium.new_context(permissions=["microphone"], color_scheme="dark", **PHONE)
    await context.add_init_script(MUTE)
    await context.add_init_script(CAPTURE)
    if mic is not None:
        ref = studio.store.put_media(mic, "wav")
        await context.add_init_script(f"window.__syntheticMic = {ref.url!r};")
    base = str(server.make_url("")).rstrip("/")
    r = await context.request.post(f"{base}/login", form={"password": PW, "confirm": PW, "next": "/"})
    assert r.ok
    page = await context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    await page.goto(f"{base}/studio/?settle=30")
    await page.wait_for_function("() => window.studio && !document.getElementById('empty').hidden")
    return page, errors


async def until(cond, timeout=60.0, every=0.1):
    t0 = asyncio.get_running_loop().time()
    while not cond():
        if asyncio.get_running_loop().time() - t0 > timeout:
            raise AssertionError("timed out")
        await asyncio.sleep(every)


@pytest.mark.skipif(os.environ.get("STUDIO_STACK") != "1", reason="STUDIO_STACK=1")
@pytest.mark.skipif(not (Path.home() / "_agent_scratch/probepack/kits/c8x4.json").is_file(), reason="needs kit c8x4")
async def test_a_spoken_turn_through_the_real_speech_models_to_an_ab(chromium, stack):
    server, studio, claude, tmp = stack
    conv = studio.conversation
    made: dict = {}

    async def ab():
        a = json.dumps({"kit": "c8x4", "knobs": {DRIVE: 0.4}, "label": "drive 40%"})
        b = json.dumps({"kit": "c8x4", "knobs": {DRIVE: 0.5}, "label": "drive 50%"})
        proc = await asyncio.create_subprocess_exec(UV, "run", "--project", str(ZPKT / "hands"), "--extra", "plans",
                                                    "hands", "plan", "ab", a, b, "--fake",
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        assert proc.returncode == 0, err.decode()[-2000:]
        made.update(json.loads(out))
        x = made["ab"]
        await conv.present_music(Path(made["path"]), made["title"], {
            "bar_seconds": x["bar_seconds"], "bars": x["bars"], "first": x["first"], "every": x["every"],
            "labels": {"A": x["a"], "B": x["b"]}}, "Listen to the kick's edge.")

    bash = {"command": "cd hands && uv run --extra plans hands plan ab A B", "description": "Render the A/B"}
    claude.script = lambda prompt: [
        TextDelta(0, "Sure. Rendering drive forty against fifty."), TextDone(0, "Sure. Rendering drive forty against fifty."),
        ToolStart("t1", "Bash", bash), ab, ToolDone("t1", "Bash", True, "ok"),
        TextDelta(1, "Here it is, A is forty percent."), TextDone(1, "Here it is, A is forty percent."),
        TurnDone("Here it is.", True, 0.01, "sess-1"),
    ]
    mic = kokoro_wav("Make the kick drive a little stronger. Tomato.", tmp / "said.wav")
    page, errors = await phone(chromium, server, studio, mic)

    await page.click("#turn")
    # Parakeet hears it, the stop word ends the turn and is taken off.
    await page.wait_for_function("() => document.querySelector('.msg--user .inline-text, .msg--user .caption')", timeout=60_000)
    await until(lambda: claude.prompts, 60)
    said = claude.prompts[0].lower()
    assert "kick" in said and "stronger" in said and "tomato" not in said, said

    # Claude's words come back as Kokoro speech; the A/B arrives and lights A and B in turn.
    await page.wait_for_function("() => document.querySelector('.msg--music')", timeout=120_000)
    assert made["rendered"] == 4 and [a["label"][:4] for a in made["ahead"]] == ["more", "the "]
    sides = set()
    for _ in range(300):
        side = await page.evaluate("document.querySelector('.msg--music.is-playing')?.dataset.side ?? null")
        if side:
            sides.add(side)
        if sides == {"A", "B"}:
            break
        await asyncio.sleep(0.05)
    assert sides == {"A", "B"}

    # Everything plays, then the mic is offered again.
    first_turn = conv.turn
    await until(lambda: conv.phase.value == "listening" and conv.turn != first_turn, 120)
    log = await page.evaluate("window.studio.engine.log")
    assert [e["kind"] for e in log if e["counted"]][:3] == ["speech", "music", "speech"] or \
        {e["kind"] for e in log if e["counted"]} == {"speech", "music"}
    assert all(e["outcome"] == "played" for e in log if e["counted"])

    # The turn was timed end to end.
    text = report(studio.store.timings(5))
    for stage in ("first_words", "stop_word", "first_audio", "music_ready", "responded", "mic_open"):
        assert stage in text, text
    assert errors == []


@pytest.mark.skipif(os.environ.get("STUDIO_CLAUDE") != "1", reason="STUDIO_CLAUDE=1 asks the real Claude")
async def test_a_typed_turn_with_real_claude(chromium, stack):
    server, studio, _, _ = stack
    page, errors = await phone(chromium, server, studio)
    await page.click("#turn")
    await page.click("#keyboard")
    await page.fill("#composer-input", "Just say hello back in five words or fewer. Do not use any tools.")
    await page.press("#composer-input", "Enter")
    # A spoken reply keeps its words in the folded caption.
    replies = "[...document.querySelectorAll('.msg--agent:not(.msg--narration):not(.msg--note) .caption-text')]"
    await page.wait_for_function(f"() => {replies}.some((e) => e.textContent.trim().length > 0)", timeout=180_000)
    reply = await page.evaluate(f"{replies}.map((e) => e.textContent).join(' ')")
    assert "hello" in reply.lower() or "hi" in reply.lower(), reply
    conv = studio.conversation
    await until(lambda: conv.phase.value == "listening", 120)
    log = await page.evaluate("window.studio.engine.log")
    assert any(e["kind"] == "speech" and e["outcome"] == "played" for e in log), log
    assert errors == []
