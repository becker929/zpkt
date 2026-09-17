"use client";

/**
 * Top bar, view area, and the player bar. Wraps everything in the player.
 *
 * This is the root layout's only child, so it is mounted once for the life of
 * the tab. Route changes replace `children` and nothing else. The player and
 * its audio element therefore outlive every navigation: a sound started in the
 * swipe view keeps playing through the detail page and the decided view
 * without reloading its stream.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { BoardProvider, useBoard } from "@/components/BoardProvider";
import { Occupancy } from "@/components/Occupancy";
import { PlayerProvider } from "@/components/PlayerProvider";
import { PlayerBar } from "@/components/PlayerBar";
import { TriageProvider, useTriage } from "@/components/TriageProvider";
import { UndoBar } from "@/components/UndoBar";
import { fetchStats } from "@/lib/api";
import { CAP_PROBLEM } from "@/lib/boardConfig";
import { formatBytes, formatCount, formatHours } from "@/lib/format";
import type { Stats } from "@/lib/types";

const MOCK = process.env.NEXT_PUBLIC_MOCK === "1";

/**
 * Decided over total, on every view.
 *
 * This is the progress bar for the whole project: every sound has to be
 * answered once, and a sound is answered when it has been taken into a project
 * or discarded. It stays in the header on a phone, where the collection totals
 * are folded away, because the totals do not change and this does.
 *
 * The split between the two is printed only when the server reports it. A zero
 * where the server said nothing would read as "nothing was taken".
 */
function TriageCounter() {
  const { counts } = useTriage();
  if (!counts || counts.total === 0) return null;
  const percent = Math.round(counts.percent);
  const split =
    counts.taken === null || counts.discarded === null
      ? ""
      : `: ${formatCount(counts.taken)} taken, ${formatCount(counts.discarded)} discarded`;
  return (
    <div
      className="triage-counter"
      data-testid="triage-counter"
      data-decided={counts.decided}
      data-total={counts.total}
      title={`${formatCount(counts.decided)} of ${formatCount(counts.total)} sounds decided${split}`}
    >
      <span className="triage-track" aria-hidden="true">
        <span className="triage-fill" style={{ width: `${Math.min(100, Math.max(percent, counts.decided > 0 ? 2 : 0))}%` }} />
      </span>
      <span className="mono">
        <span className="triage-long">
          {formatCount(counts.decided)}/{formatCount(counts.total)}{" "}
        </span>
        {percent}%
      </span>
    </div>
  );
}

/**
 * The board's occupancy, beside the triage ratio.
 *
 * The same discipline at two scales: finish what you started before starting
 * more. Triage says how much of 3,451 sounds has been dealt with; this says how
 * many of a small number of slots are taken. A column that has been pushed over
 * its cap is marked here too, so the override is visible from every view and not
 * only from the board.
 *
 * Nothing is drawn until the board answers. An absent board renders no meter
 * rather than an empty one, because zero of three is a claim and this would not
 * be entitled to make it.
 */
function BoardCounter() {
  const board = useBoard();
  if (board.status !== "ready" || !board.board) return null;
  const over = board.board.columns.filter((c) => c.over);

  return (
    <Link
      href="/board"
      className={`board-counter${over.length > 0 ? " over" : ""}`}
      data-testid="board-counter"
      data-over={over.length > 0}
      title={
        over.length > 0
          ? over.map((c) => `${c.column} is over its limit: ${c.count} of ${c.cap}`).join("; ")
          : board.board.columns.map((c) => `${c.column} ${c.count}/${c.cap}`).join("; ")
      }
    >
      {board.board.columns.map((c) => (
        <span key={c.column} className="board-counter-column" data-column={c.column} data-over={c.over}>
          <span className="board-counter-label" aria-hidden="true">
            {c.column[0]}
          </span>
          <Occupancy count={c.count} cap={c.cap} over={c.over} compact />
        </span>
      ))}
    </Link>
  );
}

/**
 * What is on screen when the configured cap could not be read.
 *
 * A cap nobody can read runs at the tightest setting, not the loosest, and this
 * is the half of that decision the user sees. Erring tight is uncomfortable, so
 * it has to say why it is uncomfortable, or somebody turning the cap down and
 * mistyping it would be left with a board they did not ask for and no way to
 * tell. It sits in the shell, so it is on every view and not only on the board.
 *
 * `NEXT_PUBLIC_COLUMN_CAP` is inlined when the code is compiled, so the server
 * and the browser render exactly the same thing and hydration stays clean.
 */
function CapProblem() {
  if (!CAP_PROBLEM) return null;
  return (
    <div className="error cap-problem" role="alert" data-testid="cap-problem">
      {CAP_PROBLEM}
    </div>
  );
}

function TopBar() {
  const pathname = usePathname();
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchStats(controller.signal)
      .then(setStats)
      .catch(() => setStats(null));
    return () => controller.abort();
  }, []);

  const link = (href: string, label: string) => (
    <Link href={href} className={pathname === href ? "active" : ""}>
      {label}
    </Link>
  );

  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-full">audio browser</span>
        <span className="brand-short" aria-hidden="true">
          ab
        </span>
        {MOCK ? <span className="mock-flag">mock data</span> : null}
      </div>
      {/* Swipe first, because it is where the work happens. The other three
          are records of it: what was decided, one sound looked up by name, and
          the board the decisions feed. */}
      <nav className="nav">
        {link("/", "swipe")}
        {link("/decided", "decided")}
        {link("/search", "search")}
        {link("/board", "board")}
      </nav>
      {/* A forced line break, and only on a phone. The header carries four
          destinations and two meters, which do not fit on 393 pixels in one
          line. Nothing is dropped and nothing scrolls off: the destinations
          take the first line and the two meters take the second. */}
      <span className="topbar-break" aria-hidden="true" />
      {/* Hours here are sounding hours: dead air is a quarter of this
          collection, and counting it overstates the listening left to do by
          about ten hours. The wall total stays in the title. */}
      <div
        className="topbar-stats mono"
        data-testid="topbar-stats"
        data-hours={stats?.total_sounding_s === null ? "wall" : "sounding"}
        title={
          stats && stats.total_sounding_s !== null
            ? `${formatHours(stats.total_sounding_s)} of sound in ${formatHours(
                stats.total_duration_s,
              )} of audio`
            : undefined
        }
      >
        {stats
          ? `${formatCount(stats.files)} sounds · ${formatHours(
              stats.total_sounding_s ?? stats.total_duration_s,
            )}${stats.total_sounding_s === null ? "" : " sounding"} · ${formatBytes(stats.total_bytes)}`
          : "…"}
      </div>
      <TriageCounter />
      <BoardCounter />
    </header>
  );
}

/**
 * The bottom of the screen.
 *
 * Every view but the swipe view gets the player bar. The swipe view has its
 * own transport under its own card, and the bottom of a phone screen is where
 * its two actions live: a second bar there would take the thumb's only
 * comfortable reach and put a "play" button where "discard" should be.
 *
 * The audio element itself lives in `PlayerProvider`, not here, so a sound
 * keeps playing across this boundary.
 */
function BottomBar() {
  const pathname = usePathname();
  if (pathname === "/") return null;
  return (
    <>
      {/* Above the player, never over it: the transport is how the sound being
          judged gets played. */}
      <UndoBar />
      <PlayerBar />
    </>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  return (
    <PlayerProvider>
      <TriageProvider>
        {/* Inside triage, because taking a sound into a project is a decision
            that changes the board, and the swipe view reads both. */}
        <BoardProvider>
          <div className="shell">
            <TopBar />
            <CapProblem />
            <div className="main">{children}</div>
            <BottomBar />
          </div>
        </BoardProvider>
      </TriageProvider>
    </PlayerProvider>
  );
}
