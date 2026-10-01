/**
 * A column's occupancy: how full it is, drawn as the slots themselves.
 *
 * The cap is the shape of the thing, not a number buried in a tooltip. Three
 * slots are three boxes; two of them full is two filled boxes. A fourth project
 * in a column of three adds a box that is visibly outside the cap and coloured
 * as a fault, so a column that has been overridden reads as wrong from across
 * the room and keeps reading that way every time the board is opened.
 *
 * The figure is printed next to it as well. The drawing is the fast read and
 * the figure is the exact one; neither is hidden behind a hover, because the
 * phone this is used on has no hover.
 */

/** The most boxes worth drawing. Past this the figure carries it. */
const MAX_SLOTS_DRAWN = 16;

export function Occupancy({
  count,
  cap,
  over,
  compact = false,
}: {
  count: number;
  cap: number;
  over: boolean;
  /** The header form: the slots only, with the figure kept for assistive text. */
  compact?: boolean;
}) {
  // Never fewer boxes than there are projects: a column holding five against a
  // cap of three has to show five. There is a ceiling on the drawing, though,
  // because somebody who has overridden twenty times needs a figure rather than
  // a wall of boxes. The figure beside it is always exact.
  const slots = Math.min(Math.max(cap, count), MAX_SLOTS_DRAWN);
  const undrawn = Math.max(cap, count) - slots;
  const label = over
    ? `over its limit: ${count} of ${cap}`
    : `${count} of ${cap} slots used`;

  return (
    <span
      className={`meter${compact ? " compact" : ""}`}
      data-testid="occupancy"
      data-count={count}
      data-cap={cap}
      data-over={over}
      role="img"
      aria-label={label}
      title={label}
    >
      <span className="pips" aria-hidden="true">
        {Array.from({ length: slots }, (_, i) => (
          <span
            key={i}
            className={`pip${i < count ? " filled" : ""}${i >= cap ? " beyond" : ""}`}
          />
        ))}
      </span>
      {undrawn > 0 ? (
        <span className="mono meter-more" aria-hidden="true">
          +{undrawn}
        </span>
      ) : null}
      {compact ? null : (
        <span className="mono meter-figure" aria-hidden="true">
          {count}/{cap}
        </span>
      )}
    </span>
  );
}
