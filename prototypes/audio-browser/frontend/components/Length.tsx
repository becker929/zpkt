/**
 * One sound's length, counted the way it is listened to.
 *
 * Sounding duration is wall duration minus every gap of two seconds or more.
 * A quarter of this collection is dead air, so a list sorted and read by wall
 * duration overstates the work by about ten hours. This component is the one
 * place that decides what a length says.
 *
 * Three cases, and the third is the one that matters:
 *
 * - The two agree: print one number.
 * - They differ by more than a few seconds: print the sounding length and mark
 *   it, because a five minute file with forty seconds of sound is usually a
 *   stem that barely plays, and that is worth knowing at a glance.
 * - Nothing has been measured: print the wall duration plainly. An unmeasured
 *   sound must never render as 0:00, which is what a missing number coerced to
 *   zero would give.
 */

import { formatDuration } from "@/lib/format";
import { differsMeaningfully } from "@/lib/silence";

export function Length({
  soundingS,
  wallS,
  className,
}: {
  soundingS: number | null | undefined;
  wallS: number | null | undefined;
  className?: string;
}) {
  const measured = soundingS !== null && soundingS !== undefined && Number.isFinite(soundingS);
  const differs = differsMeaningfully(soundingS, wallS);
  const shown = measured ? (soundingS as number) : wallS;

  const title = !measured
    ? "the whole file; its silence has not been measured"
    : differs
      ? `${formatDuration(soundingS)} of sound in ${formatDuration(wallS)}`
      : `${formatDuration(soundingS)} of sound`;

  return (
    <span
      className={`len mono${className ? ` ${className}` : ""}`}
      data-testid="length"
      data-sounding={measured ? "true" : "unknown"}
      data-differs={differs ? "true" : "false"}
      title={title}
    >
      {formatDuration(shown)}
      {differs ? (
        <span className="len-mark" aria-hidden="true">
          *
        </span>
      ) : null}
    </span>
  );
}

/**
 * A total with both numbers spelled out, for a header or a list summary.
 *
 * There is room for a sentence here, so nothing is hidden behind a mark.
 */
export function TotalLength({
  soundingS,
  wallS,
}: {
  soundingS: number | null | undefined;
  wallS: number | null | undefined;
}) {
  const measured = soundingS !== null && soundingS !== undefined && Number.isFinite(soundingS);
  if (!measured) return <span className="mono">{formatDuration(wallS)}</span>;
  if (!differsMeaningfully(soundingS, wallS)) {
    return <span className="mono">{formatDuration(soundingS)}</span>;
  }
  return (
    <span className="mono" data-testid="total-length" title="dead air is not counted">
      {formatDuration(soundingS)} sounding
      <span className="len-wall"> of {formatDuration(wallS)}</span>
    </span>
  );
}
