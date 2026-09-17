"use client";

/**
 * One audio element for the whole application, plus the queue it plays.
 *
 * The queue is a filter, not a copied list. A view hands the player the query
 * it is showing and the index of the row that was clicked. To advance, the
 * player asks the server for the single row at the next index. That keeps
 * continuous playback working over a 3,451-row filtered set without holding
 * the set in memory, and it stays correct when a filter changes.
 *
 * Sounds are addressed by hash. No filesystem path is ever sent.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { fetchFiles, fetchPeaks, fetchSilence, filesUrl, streamUrl } from "@/lib/api";
import { MIN_GAP_S, decideSkip, intervalAt, silentSeconds, skippable } from "@/lib/silence";
import type { FileRow, Peaks, Query, Silence, SilenceInterval } from "@/lib/types";

/** Where the auto-skip choice is remembered between sessions. */
const SKIP_KEY = "audio-browser.skip-silence";

interface PlayerState {
  /** The sound loaded into the audio element, or null when idle. */
  current: FileRow | null;
  /** Its peaks, once fetched. */
  peaks: Peaks | null;
  /**
   * Its measured dead air, or null when the sound has never been measured or
   * the route is not serving. Null means the player does not skip and the
   * interface shows wall duration.
   */
  silence: Silence | null;
  /** Position in the filtered set, or null when a sound was opened directly. */
  index: number | null;
  total: number;
  playing: boolean;
  /** Playhead in seconds. Comes from the audio element, not from the peaks. */
  time: number;
  /** Duration in seconds: the element's value when it has one, else the index's. */
  duration: number;
  volume: number;
  error: string | null;
  /**
   * Why the transport refused something, in one sentence for the user. Set
   * when a seek is attempted on a stream that cannot be seeked.
   */
  notice: string | null;
}

/** Shown when a seek is refused. One sentence, and it names the cause. */
export const NO_SEEK_NOTICE =
  "this file is converted from AIF as it plays, so the stream has no positions to seek to";

/**
 * Said where the unseekable notice already is.
 *
 * Skipping silence is a seek. A stream that cannot be seeked cannot be skipped
 * through, and about 1,180 paths in this collection are AIF. Saying nothing
 * would leave the setting looking broken on a third of the collection.
 */
export const NO_SKIP_NOTICE = "silence cannot be skipped in it either";

/**
 * What plays after the loaded sound.
 *
 * A filtered view hands over its query and an index: the player asks the
 * server for the single row at the next index, so a 3,451-row queue costs no
 * memory. A list is a hand-made running order that no filter reproduces, so it
 * hands over its rows instead and the player steps through them.
 */
export interface PlayQueue {
  query: Query;
  index: number;
  total: number;
  rows?: FileRow[];
}

interface PlayerApi extends PlayerState {
  /** False when the loaded stream is transcoded, so the browser cannot seek. */
  seekable: boolean;
  /**
   * Skip gaps of two seconds or more. On by default and remembered between
   * sessions.
   */
  autoSkip: boolean;
  setAutoSkip(on: boolean): void;
  /** The loaded sound's gaps at the current floor, for the waveform's tint. */
  silentRegions: SilenceInterval[];
  /**
   * Seconds of measured gap in the loaded sound, at the two second floor.
   * Zero when nothing is measured. It does not depend on the toggle: the
   * unseekable notice needs the number in order to say what is being missed.
   */
  skippableS: number;
  /** Load a row and start playing. The context defines what plays next. */
  play(row: FileRow, context?: PlayQueue): void;
  toggle(): void;
  seek(seconds: number): void;
  next(): void;
  previous(): void;
  setVolume(v: number): void;
  /**
   * Play the loaded sound over and over instead of advancing.
   *
   * This is what the swipe view runs on. One sound fills the view and repeats
   * until it is answered, so reaching the end is not a reason to move on —
   * only a decision is. Trailing silence restarts it rather than advancing the
   * queue, in exactly the same way.
   */
  loop: boolean;
  setLoop(on: boolean): void;
}

const PlayerContext = createContext<PlayerApi | null>(null);

export function usePlayer(): PlayerApi {
  const ctx = useContext(PlayerContext);
  if (!ctx) throw new Error("usePlayer must be used inside PlayerProvider");
  return ctx;
}

export function PlayerProvider({ children }: { children: ReactNode }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const queueRef = useRef<PlayQueue | null>(null);
  const peaksTokenRef = useRef(0);
  /** The loaded row, readable from callbacks that must not depend on state. */
  const currentRef = useRef<FileRow | null>(null);
  /** Peaks for the next track, fetched ahead so the waveform is instant. */
  const prefetchRef = useRef<{ hash: string; peaks: Peaks } | null>(null);
  const silenceTokenRef = useRef(0);
  /** The loaded sound's gaps at the floor, readable from the audio callbacks. */
  const gapsRef = useRef<{ hash: string; intervals: SilenceInterval[] } | null>(null);
  const autoSkipRef = useRef(true);
  /** Best known wall duration: the element's, or the row's until it has one. */
  const durationRef = useRef(0);
  /**
   * A gap the user scrubbed into on purpose.
   *
   * An explicit seek is an instruction. While the playhead sits inside this
   * gap the skipper does nothing, and the moment playback leaves it the
   * excusal is dropped. Without this the interface fights the user: every
   * attempt to listen to a quiet passage is undone a quarter of a second later.
   */
  const excusedRef = useRef<SilenceInterval | null>(null);
  /**
   * A seek made before the measurement arrived.
   *
   * The detail view loads a sound and positions it a moment later, which is
   * often before the silence route has answered. Without remembering where the
   * user aimed, a click on a tinted region would be undone the instant the
   * measurement landed — the exact fight this feature must not pick.
   */
  const pendingSeekRef = useRef<number | null>(null);
  /** The hash whose trailing silence has already advanced the queue. */
  const advancedRef = useRef<string | null>(null);

  const [state, setState] = useState<PlayerState>({
    current: null,
    peaks: null,
    silence: null,
    index: null,
    total: 0,
    playing: false,
    time: 0,
    duration: 0,
    volume: 1,
    error: null,
    notice: null,
  });
  const [loop, setLoopState] = useState(false);
  const loopRef = useRef(false);
  // On by default. The stored answer is read in an effect rather than during
  // render, because the server has no `localStorage` and a value read during
  // render would make the first client render disagree with the HTML.
  const [autoSkip, setAutoSkipState] = useState(true);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(SKIP_KEY);
      if (stored === "0") {
        autoSkipRef.current = false;
        setAutoSkipState(false);
      }
    } catch {
      /* private browsing or a blocked store: the default stands */
    }
  }, []);

  const setAutoSkip = useCallback((on: boolean) => {
    autoSkipRef.current = on;
    setAutoSkipState(on);
    try {
      window.localStorage.setItem(SKIP_KEY, on ? "1" : "0");
    } catch {
      /* the choice still holds for this session */
    }
  }, []);

  /** Fetch one row of the current queue by absolute index. */
  const rowAt = useCallback(async (queue: PlayQueue, index: number): Promise<FileRow | null> => {
    if (index < 0) return null;
    // A list carries its own running order, so there is nothing to ask for.
    if (queue.rows) return queue.rows[index] ?? null;
    const page = await fetchFiles(filesUrl(queue.query, 1, index));
    return page.items[0] ?? null;
  }, []);

  const loadPeaks = useCallback(async (hash: string) => {
    const token = (peaksTokenRef.current += 1);
    const prefetched = prefetchRef.current;
    if (prefetched && prefetched.hash === hash) {
      prefetchRef.current = null;
      setState((s) => (s.current?.hash === hash ? { ...s, peaks: prefetched.peaks } : s));
      return;
    }
    try {
      const peaks = await fetchPeaks(hash);
      if (peaksTokenRef.current !== token) return;
      setState((s) => (s.current?.hash === hash ? { ...s, peaks } : s));
    } catch {
      if (peaksTokenRef.current !== token) return;
      // A file whose peaks cannot be computed still plays; the waveform stays
      // empty rather than blocking the transport.
      setState((s) => (s.current?.hash === hash ? { ...s, peaks: { hash, buckets: 0, pairs: [] } } : s));
    }
  }, []);

  /** Set once `step` exists, so the skipper can advance the queue. */
  const stepRef = useRef<(delta: number) => void>(() => {});

  /**
   * Start the loaded sound again from the top.
   *
   * The guard that stops trailing silence advancing twice is cleared with it,
   * or the second lap would play the dead air out in full.
   */
  const restart = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    advancedRef.current = null;
    excusedRef.current = null;
    try {
      audio.currentTime = 0;
    } catch {
      return;
    }
    setState((s) => ({ ...s, time: 0 }));
    void audio.play().catch(() => {
      /* the browser refused to keep going; the transport still says so */
    });
  }, []);

  const setLoop = useCallback((on: boolean) => {
    loopRef.current = on;
    setLoopState(on);
  }, []);

  /**
   * Jump over a measured gap, or advance the queue when the gap is the end.
   *
   * Called on every `timeupdate`, on metadata, and as soon as the measurement
   * arrives, so leading silence is cut before it is heard. It reads refs only,
   * which is what lets the audio element's listeners stay subscribed once.
   */
  const maybeSkip = useCallback((t: number) => {
    const audio = audioRef.current;
    const row = currentRef.current;
    if (!audio || !row || !autoSkipRef.current) return;
    // A transcoded stream carries `Accept-Ranges: none`: there is nowhere to
    // jump to. The notice beside the waveform says so.
    if (row.transcoded) return;

    const gaps = gapsRef.current;
    if (!gaps || gaps.hash !== row.hash || gaps.intervals.length === 0) return;

    const duration =
      Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : durationRef.current;
    const decision = decideSkip({
      t,
      intervals: gaps.intervals,
      durationS: duration,
      excused: excusedRef.current,
    });

    if (!decision) {
      // Out of every gap, so an excusal has served its purpose. Inside the
      // excused one, it still holds.
      if (excusedRef.current && !intervalAt(gaps.intervals, t)) excusedRef.current = null;
      return;
    }

    if (decision.kind === "end") {
      // Trailing silence is the end of the track. Advance rather than play out
      // dead air, and only once: `timeupdate` fires four times a second.
      if (advancedRef.current === row.hash) return;
      advancedRef.current = row.hash;
      // Looping, so the end is the top. The sound repeats until it is
      // answered, and forty seconds of tail is not part of the answer.
      if (loopRef.current) {
        restart();
        return;
      }
      audio.pause();
      stepRef.current(1);
      return;
    }

    try {
      audio.currentTime = decision.to;
    } catch {
      return;
    }
    setState((s) => (s.current?.hash === row.hash ? { ...s, time: decision.to } : s));
  }, [restart]);

  /**
   * Fetch the loaded sound's dead air.
   *
   * A sound with no measurement, or a server with no silence route, yields
   * null. Nothing is skipped in that case and the interface shows wall
   * duration, which is the only length it actually knows.
   */
  const loadSilence = useCallback(
    async (hash: string, durationS: number | null) => {
      const token = (silenceTokenRef.current += 1);
      try {
        const silence = await fetchSilence(hash, MIN_GAP_S);
        if (silenceTokenRef.current !== token || currentRef.current?.hash !== hash) return;
        const intervals = skippable(
          silence?.intervals ?? [],
          MIN_GAP_S,
          silence?.duration_s ?? durationS,
        );
        gapsRef.current = { hash, intervals };
        setState((s) => (s.current?.hash === hash ? { ...s, silence } : s));

        // Honour a scrub that happened while this was in flight.
        if (pendingSeekRef.current !== null) {
          excusedRef.current = intervalAt(intervals, pendingSeekRef.current);
          pendingSeekRef.current = null;
        }
        // Cut the leading silence now rather than waiting for playback to walk
        // into it a quarter of a second later.
        const audio = audioRef.current;
        if (audio) maybeSkip(audio.currentTime);
      } catch {
        if (silenceTokenRef.current !== token) return;
        // A sound whose measurement cannot be read still plays, unskipped.
        pendingSeekRef.current = null;
        gapsRef.current = { hash, intervals: [] };
        setState((s) => (s.current?.hash === hash ? { ...s, silence: null } : s));
      }
    },
    [maybeSkip],
  );

  /** Warm the peaks cache for the track after this one. */
  const prefetchNext = useCallback(async () => {
    const queue = queueRef.current;
    if (!queue) return;
    const nextIndex = queue.index + 1;
    if (nextIndex >= queue.total) return;
    try {
      const row = await rowAt(queue, nextIndex);
      if (!row) return;
      if (prefetchRef.current?.hash === row.hash) return;
      const peaks = await fetchPeaks(row.hash);
      prefetchRef.current = { hash: row.hash, peaks };
    } catch {
      // Prefetch is best effort.
    }
  }, [rowAt]);

  const load = useCallback(
    (row: FileRow, context: PlayQueue | undefined, autoplay: boolean) => {
      queueRef.current = context ?? null;
      currentRef.current = row;
      // Nothing about the previous sound's silence applies to this one.
      gapsRef.current = null;
      excusedRef.current = null;
      pendingSeekRef.current = null;
      advancedRef.current = null;
      durationRef.current = row.duration_s ?? 0;
      setState((s) => ({
        ...s,
        current: row,
        peaks: null,
        silence: null,
        index: context?.index ?? null,
        total: context?.total ?? 0,
        time: 0,
        duration: row.duration_s ?? 0,
        error: null,
        notice: null,
      }));

      const audio = audioRef.current;
      if (audio) {
        audio.src = streamUrl(row.hash);
        audio.load();
        if (autoplay) {
          void audio.play().catch((err: unknown) => {
            setState((s) => ({ ...s, playing: false, error: String(err) }));
          });
        }
      }

      void loadPeaks(row.hash);
      void loadSilence(row.hash, row.duration_s);
      void prefetchNext();
    },
    [loadPeaks, loadSilence, prefetchNext],
  );

  const play = useCallback<PlayerApi["play"]>(
    (row, context) => {
      load(row, context, true);
    },
    [load],
  );

  const step = useCallback(
    async (delta: number) => {
      const queue = queueRef.current;
      if (!queue) return;
      const target = queue.index + delta;
      if (target < 0 || target >= queue.total) {
        setState((s) => ({ ...s, playing: false }));
        return;
      }
      const row = await rowAt(queue, target);
      if (!row) {
        setState((s) => ({ ...s, playing: false }));
        return;
      }
      load(row, { ...queue, index: target }, true);
    },
    [load, rowAt],
  );

  const next = useCallback(() => void step(1), [step]);
  const previous = useCallback(() => void step(-1), [step]);

  useEffect(() => {
    stepRef.current = (delta: number) => void step(delta);
  }, [step]);

  const toggle = useCallback(() => {
    const audio = audioRef.current;
    if (!audio || !audio.src) return;
    if (audio.paused) {
      void audio.play().catch((err: unknown) => setState((s) => ({ ...s, error: String(err) })));
    } else {
      audio.pause();
    }
  }, []);

  const seek = useCallback((seconds: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    // A transcoded stream is produced by ffmpeg as it is sent. Its length is
    // unknown until it finishes, so the server answers `Accept-Ranges: none`
    // and the browser has nowhere to jump to. Moving the read-out would only
    // make it snap back. Say why instead.
    if (currentRef.current?.transcoded) {
      setState((s) => ({ ...s, notice: NO_SEEK_NOTICE }));
      return;
    }
    const target = Math.max(0, seconds);

    // A scrub into a silent stretch is a decision to listen to it. Remember
    // which stretch, so the skipper leaves the playhead there instead of
    // yanking it forward a quarter of a second later. The excusal is dropped
    // as soon as playback moves out of that stretch.
    const gaps = gapsRef.current;
    if (gaps && gaps.hash === currentRef.current?.hash) {
      excusedRef.current = intervalAt(gaps.intervals, target);
      pendingSeekRef.current = null;
    } else {
      // The measurement has not landed yet. Hold on to where the user aimed,
      // so it can be excused the moment it does.
      excusedRef.current = null;
      pendingSeekRef.current = target;
    }
    // Scrubbing backwards out of the tail puts the end of the track back in
    // play, so the one-shot advance guard has to lift with it.
    if (currentRef.current && advancedRef.current === currentRef.current.hash) {
      advancedRef.current = null;
    }

    try {
      audio.currentTime = target;
    } catch {
      /* the element refused; leave the read-out where the element has it */
    }
    setState((s) => ({ ...s, time: target, notice: null }));
  }, []);

  const setVolume = useCallback((v: number) => {
    const clamped = Math.min(Math.max(v, 0), 1);
    const audio = audioRef.current;
    if (audio) audio.volume = clamped;
    setState((s) => ({ ...s, volume: clamped }));
  }, []);

  // Audio element events drive the transport read-out.
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const onTime = () => {
      setState((s) => ({ ...s, time: audio.currentTime }));
      maybeSkip(audio.currentTime);
    };
    const onPlay = () => setState((s) => ({ ...s, playing: true }));
    const onPause = () => setState((s) => ({ ...s, playing: false }));
    const onMeta = () => {
      if (Number.isFinite(audio.duration) && audio.duration > 0) durationRef.current = audio.duration;
      setState((s) => ({
        ...s,
        duration: Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : s.duration,
      }));
      // The element can only be positioned once it has metadata, so a skip
      // that was refused before now goes through.
      maybeSkip(audio.currentTime);
    };
    const onEnded = () => {
      // Looping means the end is not a reason to move on. Only a decision is.
      if (loopRef.current) {
        restart();
        return;
      }
      setState((s) => ({ ...s, playing: false }));
      void step(1);
    };
    const onError = () =>
      setState((s) => ({ ...s, playing: false, error: `cannot play ${s.current?.filename ?? ""}` }));

    audio.addEventListener("timeupdate", onTime);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("loadedmetadata", onMeta);
    audio.addEventListener("durationchange", onMeta);
    audio.addEventListener("ended", onEnded);
    audio.addEventListener("error", onError);
    return () => {
      audio.removeEventListener("timeupdate", onTime);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("loadedmetadata", onMeta);
      audio.removeEventListener("durationchange", onMeta);
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("error", onError);
    };
  }, [step, maybeSkip, restart]);

  // Turning the skipper on is an instruction to act now, including on the gap
  // the playhead is already sitting in.
  useEffect(() => {
    if (!autoSkip) return;
    excusedRef.current = null;
    const audio = audioRef.current;
    if (audio) maybeSkip(audio.currentTime);
  }, [autoSkip, maybeSkip]);

  // Space plays and pauses, arrows step tracks, unless a field has focus.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName)) return;
      if (event.key === " ") {
        event.preventDefault();
        toggle();
      } else if (event.key === "ArrowRight" && event.shiftKey) {
        next();
      } else if (event.key === "ArrowLeft" && event.shiftKey) {
        previous();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle, next, previous]);

  /** The gaps at the floor, computed once per measurement for the waveform. */
  const silentRegions = useMemo(
    () => skippable(state.silence?.intervals ?? [], MIN_GAP_S, state.silence?.duration_s ?? state.duration),
    [state.silence, state.duration],
  );

  const api = useMemo<PlayerApi>(
    () => ({
      ...state,
      seekable: !(state.current?.transcoded ?? false),
      autoSkip,
      setAutoSkip,
      silentRegions,
      skippableS: silentSeconds(silentRegions),
      play,
      toggle,
      seek,
      next,
      previous,
      setVolume,
      loop,
      setLoop,
    }),
    [state, autoSkip, setAutoSkip, silentRegions, play, toggle, seek, next, previous, setVolume, loop, setLoop],
  );

  return (
    <PlayerContext.Provider value={api}>
      {children}
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <audio ref={audioRef} preload="metadata" data-testid="audio" />
    </PlayerContext.Provider>
  );
}
