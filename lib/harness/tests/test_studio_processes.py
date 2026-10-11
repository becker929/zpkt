"""studio's child processes and the waits on them: the voice worker, the speaker, ffmpeg and screencapture. A process
that hangs or a wait that is cancelled must never leave a turn stuck or a process behind."""

import asyncio
import contextlib
import logging
import os
import signal
import sys
from types import SimpleNamespace

import pytest

from harness.studio import audio, grab
from harness.studio.hub import Client, Hub
from harness.studio.model import Kind, Message, Prefs
from harness.studio.speech import Speaker, Utterance, VoiceWorker, WorkerGone


class HungWorker:
    """A voice worker that takes a sentence and never answers."""

    ready = True

    async def synthesize(self, text, voice, speed):
        await asyncio.Event().wait()
        yield 0, b""


async def test_cancelling_speech_stops_a_synthesis_that_hangs():
    speaker = Speaker(HungWorker(), Hub(), None, voice="v", speed=1.0, on_update=lambda m: None,
                      on_output=lambda: None)
    speaker.start()
    utt = speaker.say(Utterance(Message(Kind.AGENT, {"text": ""}, seq=1)))
    utt.feed("Here it is.")
    utt.close()
    await asyncio.sleep(0.05)
    assert speaker.busy
    speaker.cancel()                             # an interrupt, or a typed turn
    await asyncio.wait_for(speaker.idle(), 1)
    await speaker.stop()


async def test_a_voice_worker_that_stops_answering_ends_the_sentence(monkeypatch):
    worker = VoiceWorker(["true"])
    stdin = SimpleNamespace(write=lambda data: None, is_closing=lambda: False)
    worker._proc = SimpleNamespace(returncode=None, stdin=stdin)
    worker._ready.set()
    monkeypatch.setattr(VoiceWorker, "STALL_S", 0.2, raising=False)

    async def speak():
        async for _ in worker.synthesize("Hello there.", "v", 1.0):
            pass

    with pytest.raises(WorkerGone):
        await asyncio.wait_for(speak(), 2)


async def test_the_voice_worker_does_not_inherit_the_harness_virtualenv(monkeypatch, caplog):
    # `uv run --project lib/voice` warns that VIRTUAL_ENV (the harness's) is not its project's, and ignores it.
    monkeypatch.setenv("VIRTUAL_ENV", "/elsewhere/.venv")
    show = "import os, sys; sys.stderr.write(os.environ.get('VIRTUAL_ENV', 'none') + ' ' + os.environ['EXTRA'] + '\\n')"
    worker = VoiceWorker([sys.executable, "-c", show], env={"EXTRA": "kept"})
    with caplog.at_level(logging.INFO, logger="harness.studio.speech"):
        await asyncio.wait_for(worker._run_once(), 10)
        await asyncio.sleep(0.1)
    assert "voice: none kept" in caplog.text


def _hanging_tool(tmp_path, name):
    """A stand-in for ffmpeg or screencapture that writes its pid and hangs."""
    script = tmp_path / name
    script.write_text(f"#!/bin/sh\necho $$ > {tmp_path}/{name}.pid\nexec sleep 30\n")
    script.chmod(0o755)
    return script


async def _cancel_once_started(task, pidfile):
    for _ in range(200):
        if pidfile.exists() and pidfile.read_text().strip():
            break
        await asyncio.sleep(0.01)
    pid = int(pidfile.read_text())
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    return pid


def _gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    os.kill(pid, signal.SIGKILL)                 # don't leave it behind either way
    return False


async def test_a_cancelled_encode_leaves_no_ffmpeg_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(audio, "FFMPEG", str(_hanging_tool(tmp_path, "ffmpeg")))
    task = asyncio.create_task(audio.pcm_to_mp3(b"\0" * 3200, 16_000))
    pid = await _cancel_once_started(task, tmp_path / "ffmpeg.pid")
    assert _gone(pid)


async def test_a_cancelled_screencapture_leaves_no_process_behind(tmp_path, monkeypatch):
    _hanging_tool(tmp_path, "screencapture")
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    task = asyncio.create_task(grab.screencapture())
    pid = await _cancel_once_started(task, tmp_path / "screencapture.pid")
    assert _gone(pid)


async def test_nothing_is_queued_for_a_page_whose_socket_broke():
    class BrokenSocket:
        closed = True

        async def send_str(self, _text):
            raise ConnectionResetError("gone")

    page = Client(BrokenSocket(), "phone", Prefs())
    page.send({"type": "pong"})
    await asyncio.sleep(0.01)                    # the writer finds the socket broken
    for _ in range(100):
        page.send({"type": "upsert"})            # speech, captions... until the socket handler notices
    assert page._queue.qsize() == 0
    await page.close()
