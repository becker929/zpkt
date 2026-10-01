"use client";

/**
 * The bar pinned to the bottom of every view.
 *
 * It lives in the root layout, above the router's children, so it is one
 * element for the whole application. Moving from the decided view to a detail
 * page re-renders the view area and leaves this bar and its audio element
 * mounted, which is what lets a sound keep playing across a navigation.
 *
 * It carries the same waveform component as the detail view, at a smaller
 * height, so clicking a row in the list gives an immediate picture of the sound
 * without navigating away.
 *
 * On a narrow screen it stacks: the name and the discard button on one line,
 * the read-out on the next, then the waveform and the transport side by side.
 * The name scrolls itself when it is too long to fit. See `Marquee`.
 *
 * The swipe view does not have this bar. It carries its own transport under
 * its own card, because the bottom of a phone screen is where its two answers
 * live. See `Shell`.
 */

import Link from "next/link";

import { Marquee } from "@/components/Marquee";
import { usePlayer } from "@/components/PlayerProvider";
import { useTriage } from "@/components/TriageProvider";
import { TransportButtons } from "@/components/Transport";
import { Waveform } from "@/components/Waveform";
import { formatCount, formatDuration, formatTime } from "@/lib/format";
import { NARROW, useMediaQuery } from "@/lib/useMediaQuery";

export function PlayerBar() {
  const player = usePlayer();
  const triage = useTriage();
  const narrow = useMediaQuery(NARROW);
  const row = player.current;

  /**
   * What the skipper is doing to this sound, in the read-out.
   *
   * The position and the length beside it are wall-clock, because they have to
   * agree with the waveform the playhead is moving across. This says what is
   * being taken off that, which is the number the listener actually feels.
   */
  const skipNote = () => {
    if (player.skippableS < 1) return "";
    if (row?.transcoded) return ` · ${formatDuration(player.skippableS)} silent, unskippable`;
    if (!player.autoSkip) return ` · ${formatDuration(player.skippableS)} silent`;
    return ` · skipping ${formatDuration(player.skippableS)}`;
  };

  if (!row) {
    return (
      <div className="playerbar empty" data-testid="player-idle">
        <div className="idle">tap a row to load it into the player. space plays and pauses.</div>
      </div>
    );
  }

  return (
    <div className="playerbar" data-testid="player-bar" data-hash={row.hash}>
      <div className="who">
        <div className="name">
          <Link href={`/sounds/${row.hash}`}>
            {/* The loaded sound is by definition the one being listened to, so
                its name always scrolls when it does not fit. */}
            <Marquee text={row.filename} active />
          </Link>
        </div>
        {/* One line, and it is clipped on a phone, so it runs in order of what
            the listener cannot get anywhere else: the position, why seeking is
            refused, what is being skipped, then the queue position. */}
        <div className="sub mono" data-testid="player-readout">
          {formatTime(player.time)} / {formatTime(player.duration)}
          {player.seekable ? "" : " · no seeking"}
          {skipNote()}
          {player.index !== null
            ? narrow
              ? ` · ${formatCount(player.index + 1)}/${formatCount(player.total)}`
              : ` · ${formatCount(player.index + 1)} of ${formatCount(player.total)}`
            : ""}
        </div>
      </div>

      <div className="wave-slot">
        <Waveform
          pairs={player.peaks?.pairs ?? []}
          durationS={player.duration || row.duration_s}
          progressS={player.time}
          silence={player.silentRegions}
          height={narrow ? 40 : 52}
          onSeek={(s) => player.seek(s)}
          seekable={player.seekable}
          placeholder=""
        />
        {player.notice ? (
          <div className="no-seek-note" data-testid="player-notice">
            {player.notice}
          </div>
        ) : null}
      </div>

      {/* Discard, where the thumb already is. Listening to a sound and judging
          it is one gesture; the list should not have to be scrolled back to to
          say what the sound was. Taking a sound into a project is the swipe
          view's job and is not offered here. */}
      <div className="acts">
        {/* Skipping is a playback setting, not a judgement about the sound, so
            it sits with the transport's own controls and remembers its state
            across sounds and sessions. */}
        <button
          type="button"
          className={`skip${player.autoSkip ? " on" : " off"}${row.transcoded ? " blocked" : ""}`}
          aria-pressed={player.autoSkip}
          aria-label={player.autoSkip ? "stop skipping silence" : "skip silence"}
          data-testid="skip-toggle"
          data-blocked={row.transcoded ? "true" : "false"}
          title={
            row.transcoded
              ? "this stream cannot be seeked, so silence is played through whatever this says"
              : player.autoSkip
                ? "skipping gaps of 2 seconds or more. tap to hear them."
                : "playing every gap. tap to skip gaps of 2 seconds or more."
          }
          onClick={() => player.setAutoSkip(!player.autoSkip)}
        >
          {/* A word rather than a glyph: the fast-forward character renders as
              a colour emoji on iOS, which ignores the colour that says whether
              the setting is on. Struck through, it says it is off. */}
          skip
        </button>
        <button
          type="button"
          className="drop"
          aria-label={`discard ${row.filename}`}
          title="not this one. it stops appearing; nothing is removed from disk."
          data-testid="player-discard"
          onClick={() => void triage.run("delete", [row.hash], { label: `discarded ${row.filename}` })}
        >
          ✕
        </button>
      </div>

      <TransportButtons compact />
    </div>
  );
}
