"use client";

/**
 * The board: three columns, their caps, and what is in them.
 *
 * The cap is the feature. Each column holds a small number of projects and the
 * board is drawn so that going over one is visible rather than recorded. Over
 * the limit is possible: the server refuses first, says what the cap is, and
 * takes an explicit override. After that the column stays marked until the
 * count comes back down, so an override is felt every time the board is opened
 * rather than once.
 *
 * Commit is not a column. It is the interface at a column's edge: the moment a
 * column gives a project up to the next one, freezing that column's own
 * artifact and writing a digest of it into an append-only chain. Committing out
 * of `enrich` releases the project, which leaves the board and holds no slot.
 *
 * Commit is not the only exit. **Abandon** gives the slot back without
 * promoting anything, and **revive** brings the project back to the column it
 * left, paying for the slot again. Without that, a project nobody believes in
 * holds its slot until somebody commits something they do not want, and at a cap
 * of one or two the friction is a trap. Abandoned and released projects are
 * drawn below the columns: visible, because what was tried is worth seeing, and
 * plainly not in play.
 *
 * Nothing here decodes audio and nothing here removes a file.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useBoard } from "@/components/BoardProvider";
import { TotalLength } from "@/components/Length";
import { Occupancy } from "@/components/Occupancy";
import { usePlayer } from "@/components/PlayerProvider";
import {
  ApiRefusal,
  abandonProject,
  commitProject,
  createProject,
  fetchProject,
  reviveProject,
  setProjectSound,
  type ProjectDetail,
} from "@/lib/api";
import { ENCUMBERED_AT, isEncumbered } from "@/lib/boardConfig";
import { formatCount } from "@/lib/format";
import {
  COLUMN_FREEZES,
  COLUMN_WORK,
  checkProject,
  describeIssues,
  nextPlacement,
  onBoard,
  soundSetOpen,
  storedCommit,
  type BoardColumn,
  type Column,
  type ProjectSummary,
} from "@/lib/project";
import { EMPTY_QUERY } from "@/lib/types";

const MOCK = process.env.NEXT_PUBLIC_MOCK === "1";

/** `2026-09-16T21:04:00Z` as `2026-09-16 21:04`. String work only, so the
 *  server and the browser cannot disagree about a time zone during hydration. */
function shortInstant(instant: string): string {
  return instant.length >= 16 ? `${instant.slice(0, 10)} ${instant.slice(11, 16)}` : instant;
}

/** What committing out of this column does, said plainly and in full. */
function commitConsequence(column: Column, soundCount: number): string {
  const target = nextPlacement(column);
  switch (column) {
    case "stored":
      return `This freezes the sound set. The ${formatCount(soundCount)} ${
        soundCount === 1 ? "sound" : "sounds"
      } in this project can never change again, here or in any later column, and nothing in this app reopens a frozen stage. The project moves to ${target}.`;
    case "collage":
      return `This freezes the arrangement and moves the project to ${target}. The collage view is not built yet, so there is no arrangement to freeze: the digest records the boundary, not an artifact.`;
    case "enrich":
      return "This freezes the treatment and releases the project. It leaves the board and holds no slot anywhere. The enrich view is not built yet, so the digest records the boundary, not an artifact.";
  }
}

/* The refusal panel -------------------------------------------------------- */

/**
 * What a cap refusal looks like: the server's own sentence, then one way
 * through and one way out.
 *
 * The override is labelled with what it will actually do — the number the
 * column will hold and the name of the column — because "confirm" is a word
 * people click without reading. A hard block here would only teach someone to
 * edit the configuration, which puts the decision somewhere nobody sees it.
 */
function CapRefusal({
  refusal,
  busy,
  onOverride,
  onCancel,
}: {
  refusal: ApiRefusal;
  busy: boolean;
  onOverride: () => void;
  onCancel: () => void;
}) {
  const going = refusal.cap ? refusal.cap.count + 1 : null;
  return (
    <div className="refusal" data-testid="cap-refusal" data-column={refusal.cap?.column ?? ""}>
      <p className="refusal-detail" data-testid="refusal-detail">
        {refusal.detail}
      </p>
      {refusal.cap ? (
        <p className="refusal-note">
          Going over is possible and it stays visible: {refusal.cap.column} will be marked as over its
          limit until the count comes back down.
        </p>
      ) : null}
      <div className="card-actions">
        <button
          type="button"
          className="chip override"
          data-testid="cap-override"
          disabled={busy}
          onClick={onOverride}
        >
          {going === null
            ? "do it anyway"
            : `go to ${going} in ${refusal.cap!.column} anyway`}
        </button>
        <button type="button" className="chip" data-testid="cap-cancel" disabled={busy} onClick={onCancel}>
          not now
        </button>
      </div>
    </div>
  );
}

/* One project -------------------------------------------------------------- */

type CommitStage = "idle" | "confirm" | "refused" | "blocked" | "abandon";

function ProjectCard({ project, column }: { project: ProjectSummary; column: Column }) {
  const board = useBoard();
  const player = usePlayer();
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [stage, setStage] = useState<CommitStage>("idle");
  const [refusal, setRefusal] = useState<ApiRefusal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");

  const open_ = soundSetOpen(project);
  const frozen = storedCommit(project.commits);
  const empty = project.sound_count === 0;

  const load = useCallback(() => {
    fetchProject(project.id)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [project.id]);

  useEffect(() => {
    if (open) load();
  }, [open, load, board.version]);

  const runCommit = async (override: boolean) => {
    setBusy(true);
    setError(null);
    try {
      // `column` is the stage this card is drawing, which is the stage the
      // press meant to freeze. Sending it is what stops a tab that has not seen
      // somebody else's commit from freezing the next stage by pressing the
      // same button again.
      const result = await commitProject(project.id, override, column);
      setStage("idle");
      setRefusal(null);
      setReceipt(
        result.commit
          ? `froze ${COLUMN_FREEZES[column]} at ${shortInstant(result.commit.at)}`
          : "committed",
      );
      board.refresh();
    } catch (err) {
      if (err instanceof ApiRefusal && err.cap) {
        // The downstream column is full. Overridable, and the panel says so.
        setRefusal(err);
        setStage("refused");
      } else if (err instanceof ApiRefusal) {
        // Refused for a reason that is not a cap, so no way through is offered.
        // The board is not re-read here: refreshing would move this card into
        // another column, unmount it, and take the sentence away with it. It is
        // re-read when the refusal is dismissed.
        setRefusal(err);
        setStage("blocked");
      } else {
        setError(err instanceof Error ? err.message : String(err));
        setStage("idle");
      }
    } finally {
      setBusy(false);
    }
  };

  /**
   * Let it go. The slot comes back and nothing is frozen.
   *
   * No cap can be in the way of this, so there is no override to offer and no
   * refusal panel to draw: a project that cannot be put down is a project that
   * has to be committed to be got rid of, and that is what empties the word
   * "committed" of meaning.
   */
  const runAbandon = async () => {
    setBusy(true);
    setError(null);
    try {
      await abandonProject(project.id, reason.trim());
      setStage("idle");
      setReason("");
      setReceipt(null);
      board.refresh();
    } catch (err) {
      setError(err instanceof ApiRefusal ? err.detail : err instanceof Error ? err.message : String(err));
      setStage("idle");
    } finally {
      setBusy(false);
    }
  };

  const removeSound = async (hash: string) => {
    setBusy(true);
    setError(null);
    try {
      await setProjectSound(project.id, hash, false);
      board.refresh();
      load();
    } catch (err) {
      setError(err instanceof ApiRefusal ? err.detail : err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const play = () => {
    const rows = detail?.items ?? [];
    if (rows.length === 0) return;
    player.play(rows[0], { query: EMPTY_QUERY, index: 0, total: rows.length, rows });
  };

  // The document as the server holds it, run through the shared model here as
  // well. The index already reports a file it could not read; this catches a
  // server that answered without checking, which is the case the two languages
  // exist to make impossible.
  const checked = detail?.document ? checkProject(detail.document) : null;
  const documentIssues =
    checked && !checked.ok ? describeIssues(checked.issues) : detail && !detail.valid ? detail.issues.join("; ") : null;

  return (
    <li
      className="card project-card"
      data-testid="project-card"
      data-project-id={project.id}
      data-column={project.column}
      data-sounds={project.sound_count}
      data-frozen={frozen !== null}
      data-encumbered={isEncumbered(project.sound_count)}
    >
      <div className="card-head">
        <button
          type="button"
          className="card-name project-name"
          data-testid="project-open"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          {project.name}
        </button>
        <span className="mono dim project-id" data-testid="project-id">
          {project.id}
        </span>
      </div>

      <div className="mono dim project-measures" data-testid="project-measures">
        {formatCount(project.sound_count)} {project.sound_count === 1 ? "sound" : "sounds"}
        {project.duration_s === null ? null : (
          <>
            {" · "}
            <TotalLength soundingS={project.sounding_s} wallS={project.duration_s} />
          </>
        )}
        {/* Friction, not restriction. Adding still works and the mark stays
            until the count comes back down, which is why it is beside the
            count rather than in a tooltip. */}
        {isEncumbered(project.sound_count) ? (
          <span
            className="project-encumbered"
            data-testid="project-encumbered"
            title={`more than ${ENCUMBERED_AT} sounds. a track is a kick, a rumble, a few textures and some impacts.`}
          >
            encumbered
          </span>
        ) : null}
      </div>

      {frozen ? (
        <div className="project-chain" data-testid="project-chain">
          sound set frozen {shortInstant(frozen.at)} ·{" "}
          <span className="mono" title={frozen.digest}>
            {frozen.digest.slice(0, 12)}
          </span>
          {MOCK ? <span className="dim"> (sha-256 stand-in in mock mode)</span> : null}
        </div>
      ) : null}

      {project.sound_set_verified === false ? (
        <div className="project-tamper" data-testid="project-tamper">
          The sound set no longer hashes to the digest frozen at commit. This file was edited after it
          was frozen. The digest is the record; the file is not.
        </div>
      ) : null}

      {documentIssues ? (
        <div className="project-tamper" data-testid="project-invalid">
          This project file does not match the schema: {documentIssues}
        </div>
      ) : null}

      {receipt ? (
        <div className="project-receipt" data-testid="project-receipt">
          {receipt}
        </div>
      ) : null}

      {error ? (
        <div className="sheet-problem" data-testid="project-error">
          {error}
        </div>
      ) : null}

      {stage === "confirm" ? (
        <div className="confirm" data-testid="commit-confirm">
          <p className="confirm-head">
            Commit {COLUMN_FREEZES[column]} of “{project.name}”?
          </p>
          <p className="confirm-body" data-testid="commit-consequence">
            {commitConsequence(column, project.sound_count)}
          </p>
          <div className="card-actions">
            <button
              type="button"
              className="chip freeze"
              data-testid="commit-do"
              disabled={busy}
              onClick={() => void runCommit(false)}
            >
              {column === "stored"
                ? `freeze these ${formatCount(project.sound_count)} ${
                    project.sound_count === 1 ? "sound" : "sounds"
                  }`
                : `freeze ${COLUMN_FREEZES[column]}`}
            </button>
            <button
              type="button"
              className="chip"
              data-testid="commit-cancel"
              disabled={busy}
              onClick={() => setStage("idle")}
            >
              cancel
            </button>
          </div>
        </div>
      ) : null}

      {stage === "abandon" ? (
        <div className="confirm" data-testid="abandon-confirm">
          <p className="confirm-head">Abandon “{project.name}”?</p>
          <p className="confirm-body" data-testid="abandon-consequence">
            This gives the {column} slot back without promoting anything. Nothing is frozen and nothing is
            added to the commit chain
            {frozen ? ", so the sound set stays frozen exactly as it is" : ""}. The file is kept, not
            deleted, and the project can be revived into {column} whenever there is room for it.
          </p>
          <input
            type="text"
            className="abandon-reason"
            value={reason}
            placeholder="why, if you want to say (optional)"
            aria-label={`why “${project.name}” is being abandoned`}
            data-testid="abandon-reason"
            maxLength={2000}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="card-actions">
            <button
              type="button"
              className="chip abandon"
              data-testid="abandon-do"
              disabled={busy}
              onClick={() => void runAbandon()}
            >
              abandon it
            </button>
            <button
              type="button"
              className="chip"
              data-testid="abandon-cancel"
              disabled={busy}
              onClick={() => {
                setStage("idle");
                setReason("");
              }}
            >
              keep it
            </button>
          </div>
        </div>
      ) : null}

      {stage === "refused" && refusal ? (
        <CapRefusal
          refusal={refusal}
          busy={busy}
          onOverride={() => void runCommit(true)}
          onCancel={() => {
            setStage("idle");
            setRefusal(null);
          }}
        />
      ) : null}

      {stage === "blocked" && refusal ? (
        <div className="refusal blocked" data-testid="commit-blocked">
          <p className="refusal-detail" data-testid="refusal-detail">
            {refusal.detail}
          </p>
          <div className="card-actions">
            <button
              type="button"
              className="chip"
              data-testid="blocked-dismiss"
              onClick={() => {
                setStage("idle");
                setRefusal(null);
                // Whatever this card is drawing may be out of date, which is one
                // of the ways a commit gets refused. Re-read it now.
                board.refresh();
              }}
            >
              all right
            </button>
          </div>
        </div>
      ) : null}

      {column === "stored" && empty ? (
        <p className="dim nothing-to-freeze" data-testid="nothing-to-freeze">
          nothing to freeze yet. add sounds to it from the list view.
        </p>
      ) : null}

      <div className="card-actions">
        {stage === "idle" ? (
          <button
            type="button"
            className="chip commit"
            data-testid="project-commit"
            disabled={busy || (column === "stored" && empty)}
            title={
              column === "stored" && empty
                ? "a project with no sounds has nothing to freeze"
                : `freeze ${COLUMN_FREEZES[column]} and move to ${nextPlacement(column)}`
            }
            onClick={() => {
              setReceipt(null);
              setStage("confirm");
            }}
          >
            commit {COLUMN_FREEZES[column]} → {nextPlacement(column)}
          </button>
        ) : null}
        {stage === "idle" ? (
          <button
            type="button"
            className="chip abandon"
            data-testid="project-abandon"
            disabled={busy}
            title={`give the ${column} slot back without freezing anything. the file is kept and can be revived.`}
            onClick={() => {
              setReceipt(null);
              setStage("abandon");
            }}
          >
            abandon
          </button>
        ) : null}
        <button type="button" className="chip" data-testid="project-toggle" onClick={() => setOpen((v) => !v)}>
          {open ? "hide sounds" : "show sounds"}
        </button>
      </div>

      {open ? (
        <div className="project-sounds" data-testid="project-sounds">
          {detail === null ? <span className="dim">loading…</span> : null}
          {detail !== null && detail.items.length === 0 ? (
            <span className="dim">
              {project.sound_count === 0
                ? "nothing in it yet. add sounds from the list view."
                : "none of its sounds resolve in the index."}
            </span>
          ) : null}
          {detail !== null && detail.items.length > 0 ? (
            <>
              <div className="card-actions">
                <button type="button" className="chip" data-testid="project-play" onClick={play}>
                  ▶ play
                </button>
                {detail.items.length !== project.sound_count ? (
                  <span className="dim" data-testid="project-unresolved">
                    {formatCount(project.sound_count - detail.items.length)} of its sounds are not in the
                    index
                  </span>
                ) : null}
              </div>
              <ul className="project-sound-list">
                {detail.items.map((row) => (
                  <li key={row.hash} data-testid="project-sound" data-hash={row.hash}>
                    <Link href={`/sounds/${row.hash}`}>{row.filename}</Link>
                    {open_ ? (
                      <button
                        type="button"
                        className="drop"
                        data-testid="project-sound-remove"
                        aria-label={`take ${row.filename} out of ${project.name}`}
                        title="take it out of this project. nothing is removed from disk."
                        disabled={busy}
                        onClick={() => void removeSound(row.hash)}
                      >
                        ✕
                      </button>
                    ) : null}
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

/* Starting one ------------------------------------------------------------- */

function NewProject({ projects }: { projects: ProjectSummary[] }) {
  const board = useBoard();
  const [name, setName] = useState("");
  const [refusal, setRefusal] = useState<ApiRefusal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const wanted = name.trim();
  // Names are not unique; ids are. Saying so beats refusing, and beats silently
  // making a second project that looks identical in the column.
  //
  // Every project is compared, not only the ones in `stored`. A name is reused
  // most often by somebody who has forgotten a project they already have, and
  // the ones easiest to forget are exactly the ones not in front of them:
  // committed into `collage`, abandoned, released. Comparing the column alone
  // would stay quiet in precisely those cases. Case and surrounding space are
  // ignored, because "Rust And Rebar" is the same name to a reader.
  const key = (value: string) => value.trim().toLocaleLowerCase();
  const clash = wanted === "" ? undefined : projects.find((p) => key(p.name) === key(wanted));
  const nameTaken = clash !== undefined;

  const create = async (override: boolean) => {
    if (!wanted || busy) return;
    setBusy(true);
    setError(null);
    try {
      await createProject(wanted, override);
      setName("");
      setRefusal(null);
      board.refresh();
    } catch (err) {
      if (err instanceof ApiRefusal && err.cap) setRefusal(err);
      else setError(err instanceof ApiRefusal ? err.detail : err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="new-project">
      <form
        className="new-list"
        onSubmit={(e) => {
          e.preventDefault();
          void create(false);
        }}
      >
        <input
          type="text"
          value={name}
          placeholder="new project…"
          aria-label="new project name"
          data-testid="new-project-name"
          maxLength={120}
          onChange={(e) => {
            setName(e.target.value);
            setRefusal(null);
          }}
        />
        <button type="submit" className="chip" data-testid="new-project-create" disabled={busy || !wanted}>
          start it
        </button>
      </form>

      {nameTaken ? (
        <div className="dim new-project-note" data-testid="duplicate-name" data-clash={clash!.id}>
          a project called “{clash!.name}” already exists
          {clash!.abandoned !== null
            ? ", abandoned out of " + clash!.abandoned.from + ". revive that one instead?"
            : clash!.column === "released"
              ? ", already released."
              : ` in ${clash!.column}.`}{" "}
          this makes a second one, with its own id.
        </div>
      ) : null}

      {refusal ? (
        <CapRefusal
          refusal={refusal}
          busy={busy}
          onOverride={() => void create(true)}
          onCancel={() => setRefusal(null)}
        />
      ) : null}

      {error ? (
        <div className="sheet-problem" data-testid="new-project-error">
          {error}
        </div>
      ) : null}
    </div>
  );
}

/* One column --------------------------------------------------------------- */

function ColumnView({
  info,
  projects,
}: {
  info: BoardColumn;
  /** Every project, in every placement. A column takes what is its own. */
  projects: ProjectSummary[] | null;
}) {
  // `onBoard` and not `column` alone. An abandoned project keeps the column it
  // left, because that is where revive puts it back, so matching on the column
  // would draw it in a column it is not holding a slot in and the card count
  // would disagree with the occupancy meter beside it.
  const mine = projects?.filter((p) => p.column === info.column && onBoard(p)) ?? null;

  return (
    <section
      className="board-column"
      data-testid="board-column"
      data-column={info.column}
      data-over={info.over}
      data-count={info.count}
      data-cap={info.cap}
    >
      <header className="column-head">
        <h2>{info.column}</h2>
        <Occupancy count={info.count} cap={info.cap} over={info.over} />
      </header>
      <p className="column-work">{COLUMN_WORK[info.column]}</p>

      {info.over ? (
        <p className="column-over" data-testid="column-over">
          over its limit
        </p>
      ) : null}

      {/* A file nobody can read still sits in this column and still holds its
          slot, so the occupancy counts it and there is no card for it. Saying so
          is what stops the meter and the cards looking like a mistake: it is a
          job to do, not a slot given back. */}
      {info.unreadable > 0 ? (
        <p className="column-unreadable" data-testid="column-unreadable" data-count={info.unreadable}>
          {formatCount(info.unreadable)} of these{" "}
          {info.unreadable === 1 ? "is a file that does not" : "are files that do not"} match the schema.
          {info.unreadable === 1 ? " It is" : " They are"} counted here, because a slot is held by the file
          being in the column and not by the file being right. {info.unreadable === 1 ? "It is" : "They are"}{" "}
          listed below.
        </p>
      ) : null}

      {mine === null ? (
        <p className="dim" data-testid="column-projects-unknown">
          the board reports {info.count}, but <code>/api/projects</code> is not answering, so the projects
          themselves cannot be listed.
        </p>
      ) : (
        <ul className="cards">
          {mine.map((project) => (
            <ProjectCard key={project.id} project={project} column={info.column} />
          ))}
        </ul>
      )}

      {mine !== null && mine.length === 0 && info.column !== "stored" ? (
        <p className="dim">empty. a project arrives here by being committed out of the column before it.</p>
      ) : null}

      {info.column === "stored" && projects !== null ? <NewProject projects={projects} /> : null}
    </section>
  );
}

/* Off the board ------------------------------------------------------------ */

/**
 * An abandoned project, and the way back.
 *
 * It keeps the column it left, because that is where revive puts it back, and
 * every commit it had. Reviving takes a slot like anything else, so a full
 * column refuses it with the same panel and the same override as everything
 * else here. The cost is the slot, which is the right price: bringing something
 * back is starting it again.
 */
function AbandonedCard({ project }: { project: ProjectSummary }) {
  const board = useBoard();
  const [refusal, setRefusal] = useState<ApiRefusal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const gone = project.abandoned;
  if (!gone) return null;
  const frozen = storedCommit(project.commits);

  const revive = async (override: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await reviveProject(project.id, override);
      setRefusal(null);
      board.refresh();
    } catch (err) {
      if (err instanceof ApiRefusal && err.cap) setRefusal(err);
      else setError(err instanceof ApiRefusal ? err.detail : err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <li
      className="card abandoned-card"
      data-testid="abandoned-project"
      data-project-id={project.id}
      data-from={gone.from}
      data-commits={project.commits.length}
    >
      <div className="card-head">
        <span className="card-name">{project.name}</span>
        <span className="mono dim project-id">{project.id}</span>
      </div>
      <div className="mono dim project-measures" data-testid="abandoned-measures">
        abandoned out of {gone.from} · {shortInstant(gone.at)} ·{" "}
        {formatCount(project.sound_count)} {project.sound_count === 1 ? "sound" : "sounds"}
        {frozen ? " · sound set still frozen" : ""}
      </div>
      {gone.reason ? (
        <p className="abandoned-reason" data-testid="abandoned-reason">
          “{gone.reason}”
        </p>
      ) : null}

      {error ? (
        <div className="sheet-problem" data-testid="revive-error">
          {error}
        </div>
      ) : null}

      {refusal ? (
        <CapRefusal
          refusal={refusal}
          busy={busy}
          onOverride={() => void revive(true)}
          onCancel={() => setRefusal(null)}
        />
      ) : null}

      <div className="card-actions">
        <button
          type="button"
          className="chip revive"
          data-testid="project-revive"
          disabled={busy}
          title={`put it back in ${gone.from}. it takes a slot there, and keeps every commit it has.`}
          onClick={() => void revive(false)}
        >
          revive into {gone.from}
        </button>
      </div>
    </li>
  );
}

/**
 * What is off the board: abandoned first, then released.
 *
 * Below the columns and never inside them. They hold no slot, and the record of
 * what was tried is worth seeing — this music is made by discarding most of what
 * is started. Abandoned comes first because it is the only one of the two with
 * anything left to do.
 */
function OffBoard({
  abandoned,
  released,
}: {
  abandoned: ProjectSummary[];
  released: ProjectSummary[];
}) {
  if (abandoned.length === 0 && released.length === 0) return null;
  return (
    <section className="panel off-board" data-testid="off-board">
      <h2>off the board</h2>
      <p className="dim">
        These hold no slot in any column. Nothing here is deleted: a project that was put down is kept,
        and an abandoned one can be revived into the column it left as soon as there is room for it.
      </p>

      {abandoned.length > 0 ? (
        <>
          <h3 data-testid="abandoned-head">abandoned ({formatCount(abandoned.length)})</h3>
          <ul className="cards" data-testid="abandoned-list">
            {abandoned.map((project) => (
              <AbandonedCard key={project.id} project={project} />
            ))}
          </ul>
        </>
      ) : null}

      {released.length > 0 ? (
        <>
          <h3 data-testid="released-head">released ({formatCount(released.length)})</h3>
          <p className="dim">Finished and off the board. These are what the caps are for.</p>
          <ul className="released-list" data-testid="released">
            {released.map((project) => (
              <li key={project.id} data-testid="released-project" data-project-id={project.id}>
                <span className="card-name">{project.name}</span>{" "}
                <span className="mono dim">
                  {formatCount(project.sound_count)} sounds
                  {project.commits.length > 0
                    ? ` · released ${shortInstant(project.commits[project.commits.length - 1].at)}`
                    : ""}
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}

/* The view ----------------------------------------------------------------- */

export default function BoardPage() {
  const board = useBoard();
  const all = board.projects ?? [];
  // A released project is never also abandoned — the format does not allow a
  // file to claim both — so these two lists cannot overlap.
  const abandoned = all.filter((p) => p.abandoned !== null);
  const released = all.filter((p) => p.column === "released");
  const overColumns = board.board?.columns.filter((c) => c.over) ?? [];

  return (
    <div className="detail board-view" data-testid="board">
      <h1>board</h1>
      <p className="lede">
        Three columns, each one holding a few projects at a time. Committing a column freezes what that
        column made and hands the project to the next one; committing out of enrich releases it, and it
        leaves the board. The cap is the point: finish what you started before starting more.
      </p>

      {board.status === "loading" ? <div className="notice">loading…</div> : null}

      {board.status === "absent" ? (
        <div className="notice" data-testid="board-absent">
          The board is not being served yet. <code>GET /api/board</code> and <code>GET /api/projects</code>{" "}
          answered “not here”, so there is nothing real to draw and nothing is drawn. No occupancy is shown
          rather than a made-up one.
        </div>
      ) : null}

      {board.status === "error" ? (
        <div className="error" data-testid="board-error">
          could not read the board: {board.error}
        </div>
      ) : null}

      {overColumns.length > 0 ? (
        <div className="board-alarm" data-testid="board-alarm">
          <strong>
            {overColumns
              .map((c) => `${c.column} is over its limit: ${c.count} of ${c.cap}`)
              .join(". ")}
            .
          </strong>{" "}
          Finish one before starting another. This stays here until the count comes back down.
        </div>
      ) : null}

      {board.status === "ready" && board.board === null ? (
        <div className="notice" data-testid="board-columns-absent">
          <code>GET /api/board</code> is not answering, so the caps and the occupancy are not known. The
          projects below are listed without them: an occupancy drawn from a guessed cap would be worse
          than none.
        </div>
      ) : null}

      {board.board ? (
        <div className="board" data-testid="board-columns">
          {board.board.columns.map((info) => (
            <ColumnView key={info.column} info={info} projects={board.projects} />
          ))}
        </div>
      ) : null}

      {/* Without a board there are no columns to draw, but the projects are
          still real and are still worth showing. */}
      {board.status === "ready" && board.board === null && board.projects ? (
        <ul className="cards" data-testid="board-flat">
          {board.projects
            .filter(onBoard)
            .map((project) => (
              <ProjectCard key={project.id} project={project} column={project.column as Column} />
            ))}
        </ul>
      ) : null}

      <OffBoard abandoned={abandoned} released={released} />

      {board.unreadable.length > 0 ? (
        <section className="panel unreadable" data-testid="unreadable">
          <h2>not readable</h2>
          <p className="dim">
            {formatCount(board.unreadable.length)}{" "}
            {board.unreadable.length === 1 ? "project file does" : "project files do"} not match the
            schema. They are counted in no column, because a file whose column cannot be read cannot be
            put in one. The files win over the index, so fix the file.
          </p>
          <ul className="released-list">
            {board.unreadable.map((entry) => (
              <li key={entry.id} data-testid="unreadable-project" data-project-id={entry.id}>
                <span className="mono">{entry.id}</span> <span className="dim">{entry.problem}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
