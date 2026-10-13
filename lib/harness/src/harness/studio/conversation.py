"""The turn loop: whose turn it is, what Claude is doing, and what the phone plays next.

    listening ──"tomato"──▶ working ──turn ends──▶ responding ──phone has played everything──▶ listening
        ▲                      │ (interrupt)                    │ (interrupt / tap)
        └──────────────────────┴────────────────────────────────┘

The mic and the speaker never overlap: the mic is offered only once the owner's phone has played everything it was
sent (playback.py). Each turn has an id, and work left over from a turn that something else replaced (a typed
message while the answer plays, a phone pressing Start) sees that and stops. A turn whose task fails in the app
itself hands the mic back, so whatever goes wrong, the app never stays stuck in a phase.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import audio, intents
from .activity import describe, detail
from .agent import AgentSession, TextDone, ThinkingDone, ToolStart
from .hub import Client, Hub
from .model import Kind, Message, Phase, Prefs, ShotLevel
from .narrator import Narrator, Summarize
from .playback import Playback
from .protocol import MIC_RATE
from .screens import Screens
from .speech import Speaker, Transcription, Utterance, VoiceWorker, WorkerGone
from .store import Store, new_id
from .timing import TurnClock, browser
from .turn import TurnMessages

log = logging.getLogger(__name__)

PAGE = 40                     # messages in the first page a phone gets
MAX_RECORDING_S = 600         # of one spoken turn kept for replay
TEXT_PUSH_S = 0.15            # how often a reply's growing text is pushed to the phones
INTERRUPT_S = 10.0            # how long Claude gets to stop after an interrupt before its session is dropped
SPEECH_WAIT_S = 120.0         # how often a mic waiting for speech to start checks it is still wanted
STOP_WAIT_S = 5.0             # how long stopping the server waits for the turn's tasks to end


def play_seconds(data: dict[str, Any]) -> float:
    """How long one play of a music message lasts. The Mac's play of options sweeps them, one bar each."""
    options = data.get("options")
    if options:
        return len(options["options"]) * float(options["bar_seconds"])
    return float(data.get("duration") or 0)


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
        self.to_play = Playback()          # what the owner has still to play
        self.speaker = Speaker(worker, hub, store, voice=settings.voice, speed=settings.speed,
                               on_update=self.push, on_output=self.to_play.item)
        self.narrator = Narrator(summarize, self._narrate)
        self.phase = Phase.IDLE
        self.label = ""
        self.turn: str | None = None
        self.clock: TurnClock | None = None
        self.interrupted = False                # the turn in flight was interrupted
        self._turns_offered = 0                 # since the server started: turn 1 is the cold one
        self._listening: Transcription | None = None
        self._recording = bytearray()
        self._work: asyncio.Task | None = None  # Claude's turn
        self._speech_wait: asyncio.Task | None = None   # a mic waiting for speech to start
        self._tasks: set[asyncio.Task] = set()
        self._queued: list[str] = []          # typed turns sent while Claude was working
        self._notes: list[str] = []           # what happened that Claude should hear about next turn
        self._push_later: dict[int, asyncio.TimerHandle] = {}   # growing replies, pushed at most every TEXT_PUSH_S

    # --- lifecycle -----------------------------------------------------------------------------------------------
    def start(self) -> None:
        self.speaker.start()

    async def stop(self) -> None:
        self.narrator.turn_ended()
        await self.speaker.stop()
        tasks = [t for t in self._tasks if not t.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=STOP_WAIT_S)   # so none touches the store after it is closed
        for later in self._push_later.values():
            later.cancel()
        await self.agent.close()

    def _spawn(self, coro: Coroutine[Any, Any, Any], name: str) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._reaped)
        return task

    def _reaped(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception():
            log.error("studio task %s failed", task.get_name(), exc_info=task.exception())

    def _spawn_turn(self, coro: Coroutine[Any, Any, Any], name: str) -> asyncio.Task:
        """A task that carries the current turn: if it fails, the mic goes back to Anthony."""
        return self._spawn(self._guarded(coro, self.turn), name)

    async def _guarded(self, coro: Coroutine[Any, Any, Any], turn: str | None) -> None:
        try:
            await coro
        except Exception as exc:  # noqa: BLE001 - whatever broke, the app must get back to a usable state
            log.exception("studio turn %s failed", turn)
            if self.turn == turn:
                self._recover(exc)

    def _recover(self, exc: Exception) -> None:
        """A turn failed in the app itself (Claude's own failures end its turn normally): drop what it left
        playing or listening, and give the mic back."""
        self.narrator.turn_ended()
        self.speaker.cancel()
        self.stop_audio()
        self._cancel_listening()
        self._your_turn()
        self.notice(f"Something went wrong ({type(exc).__name__}: {exc}"[:300] + "). Your turn.", "error", keep=True)

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

    def push_soon(self, msg: Message) -> None:
        """Push a growing reply (or thinking) at most every TEXT_PUSH_S (the store gets it when the block is done)."""
        if msg.seq not in self._push_later:
            self._push_later[msg.seq] = asyncio.get_running_loop().call_later(TEXT_PUSH_S, self._push_now, msg)

    def _push_now(self, msg: Message) -> None:
        self._push_later.pop(msg.seq, None)
        self.push(msg)

    def notice(self, text: str, level: str = "info", keep: bool = False) -> None:
        if keep:
            self.add(Kind.NOTICE, {"level": level, "text": text})
        else:
            self.hub.broadcast({"type": "notice", "level": level, "text": text})

    def set_phase(self, phase: Phase, label: str = "") -> None:
        self.phase, self.label = phase, label
        self.hub.broadcast({"type": "phase", "phase": phase.value, "turn": self.turn, "label": label})

    def remember_session(self, session_id: str | None) -> None:
        """Claude's session id, kept with the conversation so it resumes after a restart."""
        if session_id and session_id != self.conv.claude_session:
            self.conv.claude_session = session_id
            self.store.set_claude_session(self.conv.id, session_id)

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
            self.set_phase(Phase.IDLE)

    def start_talking(self, client: Client) -> None:
        """This phone takes the mic and the speaker, hands-free."""
        previous = self.hub.owner
        self.hub.owner = client
        client.prefs.handsfree = True
        self.to_play.reset()
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
            self.set_phase(Phase.IDLE)

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
        """A typed turn. The page it came from takes the speaker, so the answer plays where Anthony is (a page
        that only ever typed has no other way to become the owner); mid-turn it stays where it is."""
        text = text.strip()
        if self.hub.owner is not client and (self.hub.owner is None or self.phase is not Phase.WORKING):
            previous, self.hub.owner = self.hub.owner, client
            if previous is not None:
                previous.send({"type": "stop_audio"})
                if self.phase is Phase.LISTENING:
                    previous.send({"type": "unlisten", "turn": self.turn})
        if self.phase is Phase.WORKING:
            self._queued.append(text)
            self.notice("Claude is working; your message goes next.")
            return
        if self.phase is Phase.LISTENING:
            self._cancel_listening()
        self.speaker.cancel()
        self.stop_audio()
        self._begin_turn()                   # a turn still waiting for the phone to finish playing now stands down
        self._spawn_turn(self._user_turn(text, "typed", b""), "typed-turn")

    def end_turn(self, client: Client) -> None:
        if client is self.hub.owner and self._listening is not None:
            try:
                self._listening.end()
            except WorkerGone:
                self._cancel_listening()

    async def interrupt(self, client: Client) -> None:
        """Stop Claude and everything playing; the mic is Anthony's again. Returns at once: the page's socket must
        not wait on the CLI, whose own interrupt can take a minute to time out."""
        if self.phase is Phase.WORKING:
            self.interrupted = True
            self.narrator.turn_ended()
            self.speaker.cancel()
            self.stop_audio()
            self._spawn(self._stop_claude(), "interrupt")
        elif self.phase is Phase.RESPONDING:
            self.speaker.cancel()
            self.stop_audio()

    async def _stop_claude(self) -> None:
        """Ask Claude to stop (its turn ends, and _agent_turn hands the mic back); if it hasn't within INTERRUPT_S,
        drop its session: the next turn resumes it in a fresh CLI."""
        work = self._work
        asking = self._spawn(self.agent.interrupt(), "ask-claude-to-stop")
        try:
            if work is not None and not work.done():
                done, _ = await asyncio.wait({work}, timeout=INTERRUPT_S)
                if not done:
                    log.warning("Claude did not stop within %.0f s; dropping its session", INTERRUPT_S)
                    work.cancel()
                    await self.agent.close()
        finally:
            asking.cancel()

    def playback(self, client: Client, state: str, done: Any) -> None:
        client.playing = state == "busy"
        if client is self.hub.owner and isinstance(done, int):
            self.to_play.report(done, idle=state == "idle")

    def mark(self, client: Client, turn: Any, name: str, ms: Any, extra: dict[str, Any]) -> None:
        if self.clock and turn == self.turn:
            self.clock.phone(name, ms if isinstance(ms, (int, float)) else None, **extra)

    def left(self, client: Client) -> None:
        if self.hub.owner is None and self._listening is not None:
            self._cancel_listening()
            self.set_phase(Phase.IDLE)
        if self.hub.owner is None:
            self.to_play.owner_left()

    def new_conversation(self) -> None:
        if self.phase is Phase.WORKING:
            raise ValueError("Claude is working; interrupt it first.")
        self._cancel_listening()
        self.conv = self.store.new_conversation()
        self.agent.session_id = None
        self._spawn(self.agent.close(), "close-agent")
        self._notes.clear()
        self.set_phase(Phase.IDLE)
        self.hub.broadcast({"type": "reset", "conversation": self.conv.wire()})

    # --- the mic -------------------------------------------------------------------------------------------------
    def _begin_turn(self) -> None:
        self.turn = new_id("t")
        self.clock = TurnClock(self.store, self.conv.id, self.turn)

    def _offer_mic(self) -> None:
        owner = self.hub.owner
        if owner is None:
            self.set_phase(Phase.IDLE)
            return
        if not self.worker.ready:
            self.set_phase(Phase.IDLE, "Speech is starting")
            self._offer_when_ready()
            return
        self._begin_turn()
        self._turns_offered += 1
        self.clock.mark("listen", n=self._turns_offered, browser=browser(owner.ua))
        self._recording = bytearray()
        try:
            self._listening = self.worker.transcription(self.settings.stop_word, MIC_RATE)
        except WorkerGone:
            self.set_phase(Phase.IDLE, "Speech is restarting")
            self._offer_when_ready()
            return
        self._spawn_turn(self._listen(self._listening), "listen")
        self.set_phase(Phase.LISTENING)
        owner.send({"type": "listen", "turn": self.turn})

    def _your_turn(self) -> None:
        """The mic is Anthony's again: offered, if his phone is hands-free; else the app waits for Start."""
        owner = self.hub.owner
        if owner is not None and owner.prefs.handsfree:
            self._offer_mic()
        else:
            self.set_phase(Phase.IDLE)

    def _offer_when_ready(self) -> None:
        if self._speech_wait is None or self._speech_wait.done():
            self._speech_wait = self._spawn(self._wait_for_speech(), "offer-when-ready")

    async def _wait_for_speech(self) -> None:
        """Offer the mic once speech is ready, however long that takes (the first start fetches the models), as
        long as it is still wanted."""
        def wanted() -> bool:
            owner = self.hub.owner
            return self.phase is Phase.IDLE and owner is not None and owner.prefs.handsfree

        while not await self.worker.wait_ready(SPEECH_WAIT_S):
            if not wanted():
                return
        self._speech_wait = None
        if wanted():
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
        self._work = self._spawn_turn(self._agent_turn(text), "agent-turn")

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
        self.interrupted = False
        self.set_phase(Phase.WORKING, "Thinking")
        self.narrator.turn_started(text)
        self.screens.turn_started()
        messages = TurnMessages(self, self.clock)
        try:
            async for ev in self.agent.turn(self._prompt(text)):
                messages.handle(ev)
        except asyncio.CancelledError:
            if not self.interrupted:
                raise                        # the server is stopping
            asyncio.current_task().uncancel()    # Claude was dropped after an interrupt: the turn ends as usual
        except Exception as exc:  # noqa: BLE001 - tell Anthony, keep the app alive
            log.exception("agent turn failed")
            self.notice(f"Claude failed: {type(exc).__name__}: {exc}"[:400], "error", keep=True)
        finally:
            self.narrator.turn_ended()
            messages.finish(self.interrupted)
        try:
            await self.screens.turn_ended()
        except Exception:  # noqa: BLE001 - a screenshot is never worth a stuck turn
            log.exception("the turn's last screenshot failed")
        if self._queued:
            nxt = self._queued.pop(0)
            await self.speaker.idle()
            self._begin_turn()
            await self._user_turn(nxt, "typed", b"")
            return
        await self._respond()

    async def _respond(self) -> None:
        """Claude is done: wait for the phone to play everything, then hand it the mic, unless another turn has
        begun meanwhile."""
        turn, clock = self.turn, self.clock
        self.set_phase(Phase.RESPONDING)
        await self.speaker.idle()
        await self.to_play.played(lambda: self.hub.owner is not None)
        if clock:
            clock.mark("responded")
        if self.turn != turn or self.phase is not Phase.RESPONDING:
            return                                   # something else took over meanwhile
        self._your_turn()

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

    def unprompted(self, event: Any) -> None:
        """Claude acting without a turn of Anthony's (e.g. a background task it started has finished). It goes in
        the chat as a written note, thinking and activity, not spoken: the mic may be his at that moment."""
        if isinstance(event, ThinkingDone):
            self.add(Kind.THINKING, {"text": event.text, "streaming": False})
        elif isinstance(event, TextDone) and event.text.strip():
            self.add(Kind.AGENT, {"text": event.text, "role": "note", "audio": None, "duration": None,
                                  "streaming": False})
        elif isinstance(event, ToolStart):
            self.add(Kind.ACTIVITY, {"tool": event.name, "title": describe(event.name, event.input), "status": "ok",
                                     "detail": detail(event.input)})

    # --- music -----------------------------------------------------------------------------------------------------
    async def present_music(self, path: Path, title: str, ab: dict[str, Any] | None, note: str,
                            options: dict[str, Any] | None = None) -> Message:
        """A render in the chat. With `options` (tools.baked_options) the file is that many options end to end,
        `bars` bars each, and the phone switches between them itself."""
        if options:
            info = await audio.probe(path)
            want = len(options["options"]) * options["bars"] * options["bar_seconds"]
            if abs(info.duration - want) > options["bar_seconds"] / 2:
                raise ValueError(f"the file is {info.duration:.2f} s, but {len(options['options'])} options of "
                                 f"{options['bars']} bars at {options['bar_seconds']:.3f} s make {want:.2f} s")
        data, info = await audio.to_mp3(path)
        ref = await asyncio.to_thread(self.store.put_media, data, "mp3")
        msg = self.add(Kind.MUSIC, {"title": title, "audio": ref.wire(), "duration": round(info.duration, 3),
                                    "rate": info.rate, "channels": info.channels, "ab": ab, "plays": 0,
                                    "note": note, "source": path.name, "options": options})
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
            self.to_play.item(play_seconds(msg.data) * loops)
        return msg

    def last_music(self) -> Message | None:
        return self.store.last(self.conv.id, Kind.MUSIC)

    def stop_audio(self) -> None:
        if self.hub.owner is not None:
            self.hub.owner.send({"type": "stop_audio"})
        self.to_play.reset()

    # --- the agent's environment -------------------------------------------------------------------------------
    def tool_env(self) -> dict[str, str]:
        return {"STUDIO_CONVERSATION": self.conv.id}
