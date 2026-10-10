"""The turn loop: whose turn it is, what Claude is doing, and what the phone plays next.

    listening ──"tomato"──▶ working ──turn ends──▶ responding ──phone has played everything──▶ listening
        ▲                      │ (interrupt)                    │ (interrupt / tap)
        └──────────────────────┴────────────────────────────────┘

The mic and the speaker never overlap: the mic is offered only once the owner's phone reports that it has played
(or dropped) every item the Mac sent it. Items are speech streams and `play` commands; the phone counts them back
in `playback` messages, so a message lost in flight can't open the mic early.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import audio, intents
from .activity import describe, detail
from .agent import AgentSession, TextDelta, TextDone, ToolDone, ToolStart, TurnDone
from .hub import Client, Hub
from .model import Kind, Message, Phase, Prefs, ShotLevel
from .narrator import Narrator, Summarize
from .protocol import MIC_RATE
from .screens import Screens
from .speech import Speaker, Transcription, Utterance, VoiceWorker, WorkerGone
from .store import Store, new_id
from .timing import TurnClock

log = logging.getLogger(__name__)

PAGE = 40                     # messages in the first page a phone gets
MAX_RECORDING_S = 600         # of one spoken turn kept for replay
TEXT_PUSH_S = 0.15            # how often a reply's growing text is pushed to the phones
INTERRUPT_S = 10.0            # how long Claude gets to stop after an interrupt before its session is dropped
SPEECH_MAX_S = 90.0           # no utterance is longer: the latest a phone can still be playing one
PLAYBACK_SLACK_S = 15.0       # on top of an item's own length, before giving up on the phone's "done"


@dataclass
class Settings:
    stop_word: str = "tomato"
    voice: str = "af_heart"
    speed: float = 1.0
    version: str = ""


class Conversation:
    def __init__(self, *, store: Store, hub: Hub, agent: AgentSession, worker: VoiceWorker, summarize: Summarize,
                 screens: Screens, settings: Settings):
        self.store, self.hub, self.agent, self.worker = store, hub, agent, worker
        self.screens, self.settings = screens, settings
        self.conv = store.conversation()
        self.agent.session_id = self.conv.claude_session
        self.speaker = Speaker(worker, hub, store, voice=settings.voice, speed=settings.speed,
                               on_update=self.push, on_output=self._sent_item)
        self.narrator = Narrator(summarize, self._narrate)
        self.phase = Phase.IDLE
        self.label = ""
        self.turn: str | None = None
        self.clock: TurnClock | None = None
        self._listening: Transcription | None = None
        self._recording = bytearray()
        self._work: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()
        self._queued: list[str] = []          # typed turns sent while Claude was working
        self._notes: list[str] = []           # what happened that Claude should hear about next turn
        self._sent = 0                        # items sent to the owner to play
        self._done = 0                        # ... that it reports finished or dropped
        self._owner_idle = asyncio.Event()
        self._owner_idle.set()
        self._deadline = 0.0                  # when everything sent should have played, even if no "done" arrives
        self._interrupted = False
        self._push_later: dict[int, asyncio.TimerHandle] = {}   # growing replies, pushed at most every TEXT_PUSH_S

    # --- lifecycle -----------------------------------------------------------------------------------------------
    def start(self) -> None:
        self.speaker.start()

    async def stop(self) -> None:
        self.narrator.turn_ended()
        await self.speaker.stop()
        for t in [self._work, *self._tasks]:
            if t:
                t.cancel()
        await self.agent.close()

    def _spawn(self, coro: Any, name: str) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._reaped)
        return task

    def _reaped(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception():
            log.error("studio task %s failed", task.get_name(), exc_info=task.exception())

    # --- messages ------------------------------------------------------------------------------------------------
    def add(self, kind: Kind, data: dict[str, Any], level: ShotLevel | None = None) -> Message:
        msg = self.store.add(Message(kind, data, turn=self.turn, conversation=self.conv.id))
        self.hub.broadcast({"type": "upsert", "message": msg.wire()}, level)
        return msg

    def save(self, msg: Message) -> None:
        later = self._push_later.pop(msg.seq, None)
        if later is not None:
            later.cancel()                       # this push supersedes it
        self.store.update(msg)
        self.push(msg)

    def push(self, msg: Message) -> None:
        level = ShotLevel.parse(msg.data.get("level")) if msg.kind is Kind.SHOTS else None
        self.hub.broadcast({"type": "upsert", "message": msg.wire()}, level)

    def notice(self, text: str, level: str = "info", keep: bool = False) -> None:
        if keep:
            self.add(Kind.NOTICE, {"level": level, "text": text})
        else:
            self.hub.broadcast({"type": "notice", "level": level, "text": text})

    def _set_phase(self, phase: Phase, label: str = "") -> None:
        self.phase, self.label = phase, label
        self.hub.broadcast({"type": "phase", "phase": phase.value, "turn": self.turn, "label": label})

    # --- from the pages ------------------------------------------------------------------------------------------
    def welcome(self, client: Client) -> None:
        items, more = self.store.page(self.conv.id, None, PAGE)
        client.send({"type": "welcome", "conversation": self.conv.wire(), "phase": self.phase.value,
                     "turn": self.turn, "label": self.label, "version": self.settings.version,
                     "owner": self.hub.owner is client, "speech_ready": self.worker.ready,
                     "page": {"items": [m.wire() for m in items], "has_more": more}})
        if self.hub.owner is client and self.phase is Phase.LISTENING:
            client.send({"type": "listen", "turn": self.turn})

    def prefs_changed(self, client: Client, prefs: Prefs) -> None:
        was = client.prefs
        client.prefs = prefs
        if client is self.hub.owner and was.handsfree and not prefs.handsfree and self.phase is Phase.LISTENING:
            self._cancel_listening()
            self._set_phase(Phase.IDLE)

    def start_talking(self, client: Client) -> None:
        """This phone takes the mic and the speaker."""
        previous = self.hub.owner
        self.hub.owner = client
        self._sent = self._done = 0
        self._owner_idle.set()
        if previous is not None and previous is not client and self.phase is Phase.LISTENING:
            previous.send({"type": "unlisten", "turn": self.turn})
            client.send({"type": "listen", "turn": self.turn})
            return
        if self.phase in (Phase.IDLE, Phase.RESPONDING):
            self.speaker.cancel()
            self._offer_mic()
        elif self.phase is Phase.LISTENING:
            client.send({"type": "listen", "turn": self.turn})

    def pause(self, client: Client) -> None:
        client.prefs.handsfree = False
        if client is self.hub.owner and self.phase is Phase.LISTENING:
            self._cancel_listening()
            self._set_phase(Phase.IDLE)

    def mic(self, client: Client, state: str, open_ms: Any = None) -> None:
        client.mic_open = state == "open"
        if self.clock and client.mic_open and isinstance(open_ms, (int, float)):
            self.clock.phone("mic_open", open_ms)

    def hear(self, client: Client, pcm: bytes) -> None:
        if client is not self.hub.owner or self._listening is None or self._listening.closed:
            return
        try:
            self._listening.feed(pcm)
        except WorkerGone:
            return
        if len(self._recording) < MAX_RECORDING_S * MIC_RATE * 2:
            self._recording += pcm

    def typed(self, client: Client, text: str) -> None:
        text = text.strip()
        if self.phase is Phase.WORKING:
            self._queued.append(text)
            self.notice("Claude is working; your message goes next.")
            return
        if self.phase is Phase.LISTENING:
            self._cancel_listening()
        self.speaker.cancel()
        self.stop_audio()
        self._begin_turn()
        self._spawn(self._user_turn(text, "typed", b""), "typed-turn")

    def end_turn(self, client: Client) -> None:
        if client is self.hub.owner and self._listening is not None:
            try:
                self._listening.end()
            except WorkerGone:
                self._cancel_listening()

    async def interrupt(self, client: Client) -> None:
        """Stop Claude and everything playing; the mic is Anthony's again."""
        if self.phase is Phase.WORKING:
            self._interrupted = True
            self.narrator.turn_ended()
            self.speaker.cancel()
            self.stop_audio()
            await self.agent.interrupt()     # the turn ends; _agent_turn hands the mic back
            work = self._work
            if work is not None and not work.done():
                done, _ = await asyncio.wait({work}, timeout=INTERRUPT_S)
                if not done:
                    log.warning("Claude did not stop within %.0f s; dropping its session", INTERRUPT_S)
                    work.cancel()
                    await self.agent.close()      # the next turn resumes the session in a fresh CLI
        elif self.phase is Phase.RESPONDING:
            self.speaker.cancel()
            self.stop_audio()

    def playback(self, client: Client, state: str, done: Any) -> None:
        client.playing = state == "busy"
        if client is self.hub.owner and isinstance(done, int):
            self._done = max(self._done, done)
            if self._done >= self._sent and state == "idle":
                self._owner_idle.set()

    def mark(self, client: Client, turn: Any, name: str, ms: Any, extra: dict[str, Any]) -> None:
        if self.clock and turn == self.turn:
            self.clock.phone(name, ms if isinstance(ms, (int, float)) else None, **extra)

    def left(self, client: Client) -> None:
        if self.hub.owner is None and self._listening is not None:
            self._cancel_listening()
            self._set_phase(Phase.IDLE)
        if self.hub.owner is None:
            self._owner_idle.set()

    def new_conversation(self) -> None:
        if self.phase is Phase.WORKING:
            raise ValueError("Claude is working; interrupt it first.")
        self._cancel_listening()
        self.conv = self.store.new_conversation()
        self.agent.session_id = None
        self._spawn(self.agent.close(), "close-agent")
        self._notes.clear()
        self._set_phase(Phase.IDLE)
        self.hub.broadcast({"type": "reset", "conversation": self.conv.wire()})

    # --- the mic -------------------------------------------------------------------------------------------------
    def _begin_turn(self) -> None:
        self.turn = new_id("t")
        self.clock = TurnClock(self.store, self.conv.id, self.turn)

    def _offer_mic(self) -> None:
        owner = self.hub.owner
        if owner is None:
            self._set_phase(Phase.IDLE)
            return
        if not self.worker.ready:
            self._set_phase(Phase.IDLE, "Speech is starting")
            self._spawn(self._offer_when_ready(), "offer-when-ready")
            return
        self._begin_turn()
        self.clock.mark("listen")
        self._recording = bytearray()
        try:
            self._listening = self.worker.transcription(self.settings.stop_word, MIC_RATE)
        except WorkerGone:
            self._set_phase(Phase.IDLE, "Speech is restarting")
            self._spawn(self._offer_when_ready(), "offer-when-ready")
            return
        self._spawn(self._listen(self._listening), "listen")
        self._set_phase(Phase.LISTENING)
        owner.send({"type": "listen", "turn": self.turn})

    async def _offer_when_ready(self) -> None:
        if await self.worker.wait_ready(120) and self.phase is Phase.IDLE and self.hub.owner is not None:
            self._offer_mic()

    def _cancel_listening(self) -> None:
        listening, self._listening = self._listening, None
        if listening is not None:
            listening.close()
            if self.hub.owner:
                self.hub.owner.send({"type": "unlisten", "turn": self.turn})

    async def _listen(self, tr: Transcription) -> None:
        final: dict[str, Any] | None = None
        try:
            async for ev in tr.events():
                if ev["op"] == "stt.partial" and tr is self._listening:
                    self.clock.mark("first_words", once=True)
                    self.hub.broadcast({"type": "caption", "turn": self.turn, "text": ev.get("text", "")})
                elif ev["op"] == "stt.final":
                    final = ev
        except WorkerGone:
            if tr is self._listening:
                self._listening = None
                self.notice("Speech recognition restarted; say that again.", "warn")
                self._offer_mic()
            return
        if tr is not self._listening or final is None:
            return                                     # cancelled
        self._listening = None
        if self.hub.owner:
            self.hub.owner.send({"type": "unlisten", "turn": self.turn})
        self.clock.mark("stop_word" if final.get("stop_word") else "turn_ended", stt_ms=final.get("ms"),
                        audio_s=final.get("audio_s"))
        text = (final.get("text") or "").strip()
        if not text:
            self.notice("I didn't catch anything.")
            self._offer_mic()
            return
        await self._user_turn(text, "voice", bytes(self._recording))

    # --- a turn --------------------------------------------------------------------------------------------------
    async def _user_turn(self, text: str, source: str, recording: bytes) -> None:
        msg = self.add(Kind.USER, {"text": text, "source": source, "audio": None,
                                   "duration": round(len(recording) / 2 / MIC_RATE, 2) if recording else None})
        if recording:
            self._spawn(self._keep_recording(msg, recording), "keep-recording")
        intent = intents.parse(text)
        if intent is not None:
            msg.data["intent"] = intent.action
            self.save(msg)
            self._run_intent(intent, text)
            await self._respond()
            return
        self._work = asyncio.create_task(self._agent_turn(text), name="agent-turn")

    async def _keep_recording(self, msg: Message, pcm: bytes) -> None:
        try:
            mp3 = await audio.pcm_to_mp3(pcm, MIC_RATE, kbps=32)
        except audio.AudioError:
            log.exception("could not keep the recording")
            return
        msg.data["audio"] = (await asyncio.to_thread(self.store.put_media, mp3, "mp3")).wire()
        self.save(msg)

    def _run_intent(self, intent: intents.Intent, text: str) -> None:
        if intent.action == "stop":
            self.stop_audio()
            return
        music = self.store.last(self.conv.id, Kind.MUSIC)
        if music is None:
            self.notice("There is no music in this conversation yet.")
            return
        self.play(music.seq, intent.loops)
        self._notes.append(f'Anthony said "{text}", so the app played "{music.data.get("title")}" '
                           f'(music #{music.seq}) {intent.loops} time(s).')

    def _prompt(self, text: str) -> str:
        notes, self._notes = self._notes, []
        head = "".join(f"[{n}]\n" for n in notes)
        return f"{head}{text}"

    async def _agent_turn(self, text: str) -> None:
        self._interrupted = False
        self._set_phase(Phase.WORKING, "Thinking")
        self.narrator.turn_started(text)
        self.screens.turn_started()
        replies: dict[int, tuple[Message, Utterance]] = {}
        tools: dict[str, tuple[Message, float]] = {}
        clock = self.clock
        try:
            async for ev in self.agent.turn(self._prompt(text)):
                if isinstance(ev, TextDelta):
                    if ev.block not in replies:
                        replies[ev.block] = self._reply(clock)
                    msg, utt = replies[ev.block]
                    msg.data["text"] += ev.text
                    utt.feed(ev.text)
                    self.narrator.spoke()
                    clock.mark("first_text", once=True)
                    self._push_soon(msg)
                elif isinstance(ev, TextDone) and ev.block in replies:
                    msg, utt = replies.pop(ev.block)
                    msg.data.update(text=ev.text, streaming=False)
                    self.save(msg)
                    utt.close()
                elif isinstance(ev, ToolStart):
                    title = describe(ev.name, ev.input)
                    act = self.add(Kind.ACTIVITY, {"tool": ev.name, "title": title, "status": "running",
                                                   "detail": detail(ev.input)})
                    tools[ev.id] = (act, time.monotonic())
                    self._set_phase(Phase.WORKING, title)
                    self.narrator.note(title)
                    clock.mark("tool", tool=ev.name)
                elif isinstance(ev, ToolDone) and ev.id in tools:
                    act, t0 = tools.pop(ev.id)
                    act.data.update(status="ok" if ev.ok else "error", ms=round((time.monotonic() - t0) * 1000),
                                    output=ev.output[-1500:])
                    self.save(act)
                    self._set_phase(Phase.WORKING, "Thinking")
                elif isinstance(ev, TurnDone):
                    if ev.session_id and ev.session_id != self.conv.claude_session:
                        self.conv.claude_session = ev.session_id
                        self.store.set_claude_session(self.conv.id, ev.session_id)
                    clock.mark("agent_done", cost_usd=ev.cost_usd)
                    if not ev.ok and not self._interrupted:
                        self.notice(f"Claude stopped: {ev.text[:300]}", "error", keep=True)
        except asyncio.CancelledError:
            if not self._interrupted:
                raise                        # the server is stopping
        except Exception as exc:  # noqa: BLE001 - tell Anthony, keep the app alive
            log.exception("agent turn failed")
            self.notice(f"Claude failed: {type(exc).__name__}: {exc}"[:400], "error", keep=True)
        finally:
            for msg, utt in replies.values():
                msg.data["streaming"] = False
                self.save(msg)
                utt.close()
            for act, _ in tools.values():
                act.data["status"] = "error" if self._interrupted else "ok"
                self.save(act)
            self.narrator.turn_ended()
        await self.screens.turn_ended()
        if self._queued:
            nxt = self._queued.pop(0)
            await self.speaker.idle()
            self._begin_turn()
            await self._user_turn(nxt, "typed", b"")
            return
        await self._respond()

    def _reply(self, clock: TurnClock) -> tuple[Message, Utterance]:
        msg = self.add(Kind.AGENT, {"text": "", "role": "reply", "audio": None, "duration": None, "streaming": True})
        utt = self.speaker.say(Utterance(msg, on_first_audio=lambda: clock.mark("first_audio", once=True)))
        return msg, utt

    def _narrate(self, line: str) -> None:
        clock = self.clock

        def make() -> Message:
            return self.add(Kind.AGENT, {"text": line, "role": "narration", "audio": None, "duration": None,
                                         "streaming": False})

        utt = Utterance(None, make=make, droppable=True,
                        on_first_audio=lambda: clock and clock.mark("first_narration", once=True))
        self.speaker.say(utt)
        utt.feed(line)
        utt.close()

    def _push_soon(self, msg: Message) -> None:
        """Push a growing reply at most every TEXT_PUSH_S (the store gets it when the block is done)."""
        if msg.seq not in self._push_later:
            self._push_later[msg.seq] = asyncio.get_running_loop().call_later(TEXT_PUSH_S, self._push_now, msg)

    def _push_now(self, msg: Message) -> None:
        self._push_later.pop(msg.seq, None)
        self.push(msg)

    async def _respond(self) -> None:
        """Claude is done: wait for the phone to play everything, then hand it the mic."""
        self._set_phase(Phase.RESPONDING)
        await self.speaker.idle()
        while self.hub.owner is not None and self._done < self._sent:
            self._owner_idle.clear()
            wait = self._deadline - time.monotonic()
            if wait <= 0:
                log.warning("the phone never reported playing %d of %d items; going on", self._sent - self._done,
                            self._sent)
                break
            try:
                await asyncio.wait_for(self._owner_idle.wait(), wait)
            except asyncio.TimeoutError:
                pass
        if self.clock:
            self.clock.mark("responded")
        if self.phase is not Phase.RESPONDING:
            return                                   # something else took over meanwhile
        owner = self.hub.owner
        if owner is not None and owner.prefs.handsfree:
            self._offer_mic()
        else:
            self._set_phase(Phase.IDLE)

    # --- music -----------------------------------------------------------------------------------------------------
    async def present_music(self, path: Path, title: str, ab: dict[str, Any] | None, note: str) -> Message:
        data, info = await audio.to_flac(path)
        ref = await asyncio.to_thread(self.store.put_media, data, "flac")
        msg = self.add(Kind.MUSIC, {"title": title, "audio": ref.wire(), "duration": round(info.duration, 3),
                                    "rate": info.rate, "channels": info.channels, "ab": ab, "plays": 0,
                                    "note": note, "source": path.name})
        if self.clock:
            self.clock.mark("music_ready", seq=msg.seq)
        if self.hub.autoplay:
            self.play(msg.seq, 1)
        return msg

    def play(self, seq: int, loops: int) -> Message:
        msg = self.store.get(seq)
        if msg is None or msg.kind is not Kind.MUSIC or msg.conversation != self.conv.id:
            raise ValueError(f"no music #{seq} in this conversation")
        msg.data["plays"] = int(msg.data.get("plays", 0)) + loops
        self.save(msg)
        if self.hub.to_owner({"type": "play", "seq": seq, "loops": loops}):
            self._sent_item(float(msg.data.get("duration") or 0) * loops)
        return msg

    def last_music(self) -> Message | None:
        return self.store.last(self.conv.id, Kind.MUSIC)

    def stop_audio(self) -> None:
        if self.hub.owner is not None:
            self.hub.owner.send({"type": "stop_audio"})
        self._sent = self._done = 0
        self._owner_idle.set()

    def _sent_item(self, seconds: float | None = None) -> None:
        """One more item for the owner to play; it should be done within `seconds` (plus slack) of now. A speech
        stream's length isn't known when it starts, so it gets the longest an utterance can be."""
        self._sent += 1
        self._owner_idle.clear()
        length = SPEECH_MAX_S if seconds is None else seconds
        self._deadline = max(self._deadline, time.monotonic() + length + PLAYBACK_SLACK_S)

    # --- the agent's environment -------------------------------------------------------------------------------
    def tool_env(self) -> dict[str, str]:
        return {"STUDIO_CONVERSATION": self.conv.id}
