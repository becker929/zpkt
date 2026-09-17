"use client";

/**
 * Detail view: one sound.
 *
 * The alias panel is the point of this page. A hash is the identity of a sound
 * and a path is only a name for it, so a sound with three paths is listed with
 * all three. Duplication is shown, not hidden.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { NO_SEEK_NOTICE, NO_SKIP_NOTICE, usePlayer } from "@/components/PlayerProvider";
import { useTriage } from "@/components/TriageProvider";
import { Transport } from "@/components/Transport";
import { Waveform } from "@/components/Waveform";
import { fetchDetail, fetchPeaks, fetchSilence, fetchSpans } from "@/lib/api";
import { formatBytes, formatCount, formatDuration } from "@/lib/format";
import { isBundlePath, pathsVerdict } from "@/lib/paths";
import { MIN_GAP_S, differsMeaningfully, silentSeconds, skippable } from "@/lib/silence";
import type { FileDetail, Peaks, Silence, Span } from "@/lib/types";

export default function SoundPage() {
  const params = useParams<{ hash: string }>();
  const hash = typeof params.hash === "string" ? params.hash : "";
  const player = usePlayer();
  const triage = useTriage();

  const [detail, setDetail] = useState<FileDetail | null>(null);
  /**
   * The discard state this page has changed, before a re-fetch confirms it.
   *
   * Without it the button would keep saying "discard" after discarding, which
   * reads as a failure.
   */
  const [discarded, setDiscarded] = useState<boolean | null>(null);
  const [peaks, setPeaks] = useState<Peaks | null>(null);
  const [spans, setSpans] = useState<Span[]>([]);
  /**
   * Which classifier's spans the waveform is showing.
   *
   * Every method writes into the same table, so a sound can carry three
   * opinions at once. Drawing all of them would tint the same second three
   * times over and say nothing. Null means "the first method this sound has",
   * which is what the page falls back to before anything is picked.
   */
  const [spanMethod, setSpanMethod] = useState<string | null>(null);
  /** This sound's dead air, or null when it has never been measured. */
  const [silence, setSilence] = useState<Silence | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!hash) return;
    const controller = new AbortController();
    setDetail(null);
    setPeaks(null);
    setSpans([]);
    setSpanMethod(null);
    setSilence(null);
    setError(null);
    setDiscarded(null);

    fetchDetail(hash, controller.signal)
      .then(setDetail)
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : String(err));
      });

    fetchPeaks(hash, controller.signal)
      .then(setPeaks)
      .catch(() => {
        if (!controller.signal.aborted) setPeaks({ hash, buckets: 0, pairs: [] });
      });

    // Stage 3 populates this. A missing route yields an empty list, so the
    // waveform simply draws without tints.
    fetchSpans(hash, undefined, controller.signal)
      .then(setSpans)
      .catch(() => setSpans([]));

    // An unmeasured sound, or a server with no silence route, answers null.
    // The page then shows wall duration and tints nothing, which is the truth.
    fetchSilence(hash, MIN_GAP_S, controller.signal)
      .then(setSilence)
      .catch(() => setSilence(null));

    return () => controller.abort();
  }, [hash]);

  // Every method that wrote a span for this sound, in the order they arrived.
  const spanMethods = Array.from(
    new Set(spans.map((span) => span.method).filter((name): name is string => Boolean(name))),
  );
  const shownMethod = spanMethod ?? spanMethods[0] ?? null;
  // A sound classified before `method` was recorded has spans with no method.
  // Showing them is better than showing nothing, so an empty method list means
  // "draw everything".
  const shownSpans = shownMethod ? spans.filter((span) => span.method === shownMethod) : spans;

  const isCurrent = player.current?.hash === hash;
  const favorite = player.favoriteOverrides[hash] ?? detail?.favorite ?? false;
  const isDiscarded = discarded ?? detail?.deleted ?? false;

  const onSeek = useCallback(
    (seconds: number) => {
      if (!detail) return;
      if (!isCurrent) {
        player.play(detail);
        // The element needs a source before it can be positioned.
        setTimeout(() => player.seek(seconds), 120);
        return;
      }
      player.seek(seconds);
    },
    [detail, isCurrent, player],
  );

  if (error) {
    return (
      <div className="detail">
        <div className="error">could not load this sound: {error}</div>
        <p>
          <Link href="/">back to the list</Link>
        </p>
      </div>
    );
  }

  if (!detail) return <div className="notice">loading…</div>;

  const verdict = pathsVerdict(detail.aliases, detail.size_bytes);

  // Gaps at the two second floor: what is tinted, and what the player jumps.
  const gaps = skippable(silence?.intervals ?? [], MIN_GAP_S, silence?.duration_s ?? detail.duration_s);
  const silentS = silentSeconds(gaps);
  const soundingS = silence?.sounding_s ?? detail.sounding_s;
  const shortened = differsMeaningfully(soundingS, detail.duration_s);

  return (
    <div className="detail" data-testid="detail" data-hash={detail.hash}>
      <h1 data-testid="detail-name">{detail.filename}</h1>
      <div className="hash mono">{detail.hash}</div>

      <div className="panel">
        <Waveform
          pairs={peaks?.pairs ?? []}
          durationS={(isCurrent ? player.duration : 0) || detail.duration_s}
          progressS={isCurrent ? player.time : 0}
          spans={shownSpans}
          silence={gaps}
          height={150}
          onSeek={onSeek}
          seekable={!detail.transcoded}
        />
        {detail.transcoded ? (
          <div className="no-seek-note" data-testid="no-seek-note">
            {NO_SEEK_NOTICE}. It plays from the start
            {silentS >= 1 ? `, and ${NO_SKIP_NOTICE}: ${formatDuration(silentS)} of it is silent` : `, and ${NO_SKIP_NOTICE}`}.
          </div>
        ) : null}
        <Transport />
        <div className="transport" style={{ marginTop: 10 }}>
          <button
            type="button"
            className={`chip${favorite ? " on" : ""}`}
            data-testid="detail-favorite"
            aria-pressed={favorite}
            onClick={() => void player.toggleFavorite({ ...detail, favorite })}
          >
            {favorite ? "★ favorite" : "☆ mark favorite"}
          </button>
          <button
            type="button"
            className={`chip ${isDiscarded ? "restore" : "discard"}`}
            data-testid="detail-discard"
            aria-pressed={isDiscarded}
            title={
              isDiscarded
                ? "put this sound back in the list"
                : "not this one. it stops appearing; every copy stays on disk."
            }
            onClick={() => {
              const next = !isDiscarded;
              setDiscarded(next);
              void triage.run(next ? "delete" : "restore", [detail.hash], {
                label: `${next ? "discarded" : "restored"} ${detail.filename}`,
              });
            }}
          >
            {isDiscarded ? "↩ discarded — restore" : "✕ discard"}
          </button>
          {!isCurrent ? (
            <button type="button" className="chip" data-testid="detail-play" onClick={() => player.play(detail)}>
              load into player
            </button>
          ) : null}
          {/* Only where there is something to skip. The setting is global and
              persists; the player bar carries it on every other view. */}
          {gaps.length > 0 && !detail.transcoded ? (
            <button
              type="button"
              className={`chip${player.autoSkip ? " on" : ""}`}
              data-testid="detail-skip-toggle"
              aria-pressed={player.autoSkip}
              title="gaps of 2 seconds or more. a scrub into one stays there."
              onClick={() => player.setAutoSkip(!player.autoSkip)}
            >
              {player.autoSkip
                ? `skipping ${formatDuration(silentS)} of silence`
                : `playing ${formatDuration(silentS)} of silence`}
            </button>
          ) : null}
          {spans.length > 0 ? (
            <span className="chip">{formatCount(shownSpans.length)} labelled spans</span>
          ) : null}
          {spanMethods.length > 1
            ? spanMethods.map((name) => (
                <button
                  key={name}
                  type="button"
                  className={`chip${name === shownMethod ? " on" : ""}`}
                  data-testid={`span-method-${name}`}
                  aria-pressed={name === shownMethod}
                  title={`show the spans ${name} found`}
                  onClick={() => setSpanMethod(name)}
                >
                  {name}
                </button>
              ))
            : null}
        </div>
      </div>

      <div className="panel">
        <h2>metadata</h2>
        <dl className="meta-grid">
          {/* Sounding first: it is the length that says how long this takes to
              listen to. Wall duration stays beside it, because the gap between
              the two is itself informative. */}
          <div>
            <dt>sounding</dt>
            <dd className="mono" data-testid="detail-sounding" data-differs={shortened ? "true" : "false"}>
              {soundingS === null || soundingS === undefined ? "—" : formatDuration(soundingS)}
            </dd>
          </div>
          <div>
            <dt>length</dt>
            <dd className="mono" data-testid="detail-wall">
              {formatDuration(detail.duration_s)}
            </dd>
          </div>
          <div>
            <dt>silence</dt>
            <dd className="mono" data-testid="detail-silence">
              {silence === null
                ? "not measured"
                : gaps.length === 0
                  ? "none"
                  : `${formatDuration(silentS)} in ${gaps.length}`}
            </dd>
          </div>
          <div>
            <dt>size</dt>
            <dd className="mono">{formatBytes(detail.size_bytes)}</dd>
          </div>
          <div>
            <dt>format</dt>
            <dd className="mono">{detail.ext.replace(".", "") || "—"}</dd>
          </div>
          <div>
            <dt>codec</dt>
            <dd className="mono">{detail.codec ?? "—"}</dd>
          </div>
          <div>
            <dt>sample rate</dt>
            <dd className="mono">{detail.sample_rate ? `${formatCount(detail.sample_rate)} Hz` : "—"}</dd>
          </div>
          <div>
            <dt>channels</dt>
            <dd className="mono">{detail.channels ?? "—"}</dd>
          </div>
          <div>
            <dt>paths</dt>
            <dd className="mono">{detail.aliases.length}</dd>
          </div>
          <div>
            <dt>tags</dt>
            <dd>{detail.tags.length > 0 ? detail.tags.join(", ") : "—"}</dd>
          </div>
        </dl>
      </div>

      <div className="panel">
        <h2>paths ({detail.aliases.length})</h2>
        {verdict.kind === "reclaimable" ? (
          <div className="dupe-note" data-testid="dupe-note" data-reclaimable="true">
            Stored {verdict.copies} times inside one root. Keeping one frees{" "}
            {formatBytes(verdict.freedBytes)}.
          </div>
        ) : null}
        {verdict.kind === "bundle" ? (
          <div className="dupe-note" data-testid="dupe-note" data-reclaimable="false">
            Stored {verdict.copies} times inside one root, and every copy is a Logic
            project&rsquo;s own media. Each project reads this file from its own bundle, and
            those projects exist only in the read-only originals. Nothing here can be
            reclaimed.
          </div>
        ) : null}
        {verdict.kind === "mirror" ? (
          <div className="mirror-note" data-testid="mirror-note">
            One copy per root, across {verdict.roots} roots. This is the working copy, not
            wasted space.
          </div>
        ) : null}
        <ul className="alias-list" data-testid="alias-list">
          {detail.aliases.map((alias, i) => (
            <li key={alias.path} data-testid="alias" data-in-bundle={isBundlePath(alias.path)}>
              <span className="n mono">{i + 1}</span>
              {alias.root ? <span className="root">{alias.root}</span> : null}
              <span className="path mono">{alias.path}</span>
              {isBundlePath(alias.path) ? (
                <span className="locked" data-testid="alias-locked" title="inside a Logic project bundle">
                  in a project
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
