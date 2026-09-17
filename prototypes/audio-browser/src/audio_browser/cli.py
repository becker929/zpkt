"""Command line entry point.

``scan``, ``dupes``, ``stats``, ``peaks``, ``serve``, ``search``, ``dedupe``.
Only ``dedupe --apply`` removes a file; everything else reads.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from . import silence
from .config import Config, ConfigError, default_projects, load_config
from .db import connect, now_iso, open_db
from .dedupe import (
    UnsafeDeletion,
    apply_plan,
    example_lines,
    plan_root,
    write_plan,
)
from .peaks import BUCKETS, PeaksError, ensure_peaks
from .report import collect_stats, duplicate_groups, duplicate_summary, redundancy
from .scan import DEFAULT_BATCH, DEFAULT_WORKERS, scan_roots

DEFAULT_SUBJECT_ROOT = "audio-library"
DEFAULT_REFERENCE_ROOT = "compost"

# Repeated here rather than imported so that `--help` does not pull in the
# segment package, which in turn would not pull in TensorFlow, but the principle
# of keeping the parser free of optional imports is worth holding to.
SEGMENT_METHODS = ("yamnet", "vad", "clap")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="audio-browser",
        description="Content-addressed index of an audio collection.",
    )
    parser.add_argument(
        "--config", type=Path, default=None, help="path to config.toml"
    )
    parser.add_argument(
        "--db", type=Path, default=None, help="override the database path"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="walk the roots and index them")
    p_scan.add_argument("--root", action="append", help="scan only this root name")
    p_scan.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p_scan.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    p_scan.add_argument(
        "--no-prune",
        dest="prune",
        action="store_false",
        help="keep aliases whose file has disappeared",
    )
    p_scan.add_argument(
        "--no-probe",
        dest="probe",
        action="store_false",
        help="skip ffprobe; hash only",
    )
    p_scan.add_argument(
        "--reprobe", action="store_true", help="probe every blob again"
    )
    p_scan.add_argument("--quiet", action="store_true")
    p_scan.set_defaults(func=cmd_scan, prune=True, probe=True)

    p_dupes = sub.add_parser("dupes", help="report duplicate blobs")
    p_dupes.add_argument(
        "--limit",
        type=int,
        default=20,
        help="how many duplicate groups to print; 0 for none, -1 for all",
    )
    p_dupes.add_argument("--subject", default=None, help="root to test for redundancy")
    p_dupes.add_argument("--against", default=None, help="root to test against")
    p_dupes.set_defaults(func=cmd_dupes)

    p_dedupe = sub.add_parser(
        "dedupe",
        help="remove copies of a sound that repeat inside one root",
        description=(
            "Propose, and with --apply carry out, the removal of paths that "
            "hold a sound another path in the same root already holds. Dry run "
            "unless --apply is given. --root has no default on purpose."
        ),
    )
    p_dedupe.add_argument(
        "--root",
        required=True,
        help="the one root to deduplicate; nothing outside it is ever touched",
    )
    p_dedupe.add_argument(
        "--apply",
        action="store_true",
        help="actually delete the files. Without this the command only reports.",
    )
    p_dedupe.add_argument(
        "--plan-out",
        type=Path,
        default=None,
        help="write the full proposed deletion list to this file",
    )
    p_dedupe.add_argument(
        "--examples", type=int, default=10, help="how many example lines to print"
    )
    p_dedupe.set_defaults(func=cmd_dedupe)

    p_stats = sub.add_parser("stats", help="summarise the index")
    p_stats.set_defaults(func=cmd_stats)

    p_peaks = sub.add_parser("peaks", help="compute and cache waveform peaks")
    p_peaks.add_argument("--hash", default=None, help="one blob hash")
    p_peaks.add_argument(
        "--limit", type=int, default=0, help="compute for N blobs that lack peaks"
    )
    p_peaks.set_defaults(func=cmd_peaks)

    p_serve = sub.add_parser("serve", help="run the HTTP API")
    p_serve.add_argument("--host", default=None, help="bind address")
    p_serve.add_argument("--port", type=int, default=None, help="bind port")
    p_serve.set_defaults(func=cmd_serve)

    p_search = sub.add_parser("search", help="full-text search over filenames")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=20)
    p_search.set_defaults(func=cmd_search)

    p_segment = sub.add_parser(
        "segment",
        help="label spans of speech, music and other with one classifier",
        description=(
            "Run one classifier over every sound that has not been discarded "
            "and write its spans. Restartable: a sound that already has a run "
            "record for this method is skipped unless --force is given. "
            "Reads audio; writes only to the index."
        ),
    )
    p_segment.add_argument(
        "method", choices=list(SEGMENT_METHODS), help="which classifier to run"
    )
    p_segment.add_argument(
        "--limit", type=int, default=0, help="stop after N sounds; 0 means all"
    )
    p_segment.add_argument(
        "--max-duration",
        type=float,
        default=0.0,
        help="skip sounds longer than this many seconds; 0 means no limit",
    )
    p_segment.add_argument(
        "--include-discarded",
        action="store_true",
        help="also classify sounds the user has discarded (off by default)",
    )
    p_segment.add_argument(
        "--force", action="store_true", help="redo sounds that already have a run"
    )
    p_segment.add_argument("--quiet", action="store_true")
    p_segment.set_defaults(func=cmd_segment)

    p_silence = sub.add_parser(
        "silence",
        help="measure dead air so the player can skip it",
        description=(
            "Run ffmpeg over every sound that has no silence row and store "
            "every gap down to 0.4 seconds. Restartable: a sound that already "
            "has a row is skipped unless --force is given. Reads audio; writes "
            "only to the index."
        ),
    )
    p_silence.add_argument("--hash", default=None, help="measure one blob hash")
    p_silence.add_argument(
        "--limit", type=int, default=0, help="stop after N sounds; 0 means all"
    )
    p_silence.add_argument(
        "--include-discarded",
        action="store_true",
        help="also measure sounds the user has discarded (off by default)",
    )
    p_silence.add_argument(
        "--force", action="store_true", help="re-measure sounds that already have a row"
    )
    p_silence.add_argument("--quiet", action="store_true")
    p_silence.set_defaults(func=cmd_silence)

    p_projects = sub.add_parser(
        "projects",
        help="list the board, or rebuild its index from the project files",
        description=(
            "The files in the projects directory are the truth. This prints "
            "what they say, and --rebuild throws the SQLite cache away and "
            "derives it again from them."
        ),
    )
    p_projects.add_argument(
        "--rebuild",
        action="store_true",
        help="drop the cached index and build it again from the directory",
    )
    p_projects.set_defaults(func=cmd_projects)

    p_bakeoff = sub.add_parser(
        "bakeoff",
        help="report where the classifiers agree and where they do not",
        description=(
            "Compare the stored spans of two or more methods. Reads only. "
            "With no --method, every method that has written a span is used."
        ),
    )
    p_bakeoff.add_argument(
        "--method", action="append", default=None, help="a method to include"
    )
    p_bakeoff.add_argument(
        "--examples", type=int, default=5, help="how many disputed sounds to show"
    )
    p_bakeoff.set_defaults(func=cmd_bakeoff)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    db_path: Path = args.db or config.db_path
    try:
        result = args.func(args, config, db_path)
    except sqlite3.OperationalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except UnsafeDeletion as exc:
        # The index and the root disagree. Stopping is the correct outcome.
        print(f"error: {exc}", file=sys.stderr)
        return 3
    return int(result or 0)


def cmd_scan(args: argparse.Namespace, config: Config, db_path: Path) -> int:
    roots = list(config.roots)
    if args.root:
        wanted = set(args.root)
        unknown = wanted - {r.name for r in roots}
        if unknown:
            print(f"error: unknown root(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        roots = [r for r in roots if r.name in wanted]

    def log(message: str) -> None:
        if not args.quiet:
            print(message, file=sys.stderr, flush=True)

    conn = open_db(db_path)
    try:
        stats = scan_roots(
            conn,
            roots,
            workers=args.workers,
            batch_size=args.batch,
            prune=args.prune,
            probe=args.probe,
            reprobe=args.reprobe,
            log=log,
        )
    finally:
        conn.close()

    print(f"database {db_path}")
    for line in stats.as_lines():
        print(line)
    if stats.roots_skipped:
        print(f"roots skipped    {', '.join(stats.roots_skipped)}")
    return 0


def cmd_dupes(args: argparse.Namespace, config: Config, db_path: Path) -> int:
    conn = _read_only(db_path)
    try:
        # The command exists to answer "is this root fully redundant against
        # that one", which is a cross-root question, so every alias counts.
        summary = duplicate_summary(conn, within_root=False)
        limit = None if args.limit < 0 else args.limit
        if limit != 0:
            groups = duplicate_groups(conn, limit=limit)
            for group in groups:
                print(
                    f"{group.file_hash[:16]}  {human_bytes(group.size_bytes)}  "
                    f"x{group.copies}  wastes {human_bytes(group.wasted_bytes)}"
                )
                for path in group.paths:
                    print(f"    {path}")
            if limit is not None and summary.groups > len(groups):
                print(f"... {summary.groups - len(groups)} more groups")
            print()

        print("duplicate summary")
        print(f"  duplicated blobs   {summary.groups}")
        print(f"  extra copies       {summary.extra_copies}")
        print(f"  wasted bytes       {human_bytes(summary.wasted_bytes)}")
        print()

        subject = args.subject or DEFAULT_SUBJECT_ROOT
        reference = args.against or DEFAULT_REFERENCE_ROOT
        known = {r.name for r in config.roots}
        if subject not in known or reference not in known:
            print(
                f"skipping redundancy check: roots {subject!r} and {reference!r} "
                f"are not both configured",
                file=sys.stderr,
            )
            return 0

        rep = redundancy(conn, subject, reference)
        print(f"redundancy of {subject!r} against {reference!r}")
        print(
            f"  blobs under {subject}      {rep.subject_blobs} "
            f"({human_bytes(rep.subject_bytes)})"
        )
        print(
            f"  with a twin in {reference}   {rep.twinned_blobs} "
            f"({human_bytes(rep.twinned_bytes)})"
        )
        print(
            f"  without a twin             {rep.untwinned_blobs} "
            f"({human_bytes(rep.untwinned_bytes)})"
        )
        if rep.untwinned_examples:
            print("  largest untwinned blobs:")
            for _, path, size in rep.untwinned_examples:
                print(f"    {human_bytes(size):>10}  {path}")
        print()
        if rep.fully_redundant:
            print(
                f"VERDICT: every blob under {subject!r} also exists under "
                f"{reference!r}. The copy is fully redundant."
            )
        elif rep.subject_blobs == 0:
            print(f"VERDICT: nothing indexed under {subject!r}.")
        else:
            print(
                f"VERDICT: {rep.untwinned_blobs} blobs under {subject!r} have no "
                f"twin under {reference!r}. Do not delete it yet."
            )
        print("This command never deletes anything.")
    finally:
        conn.close()
    return 0


def cmd_dedupe(args: argparse.Namespace, config: Config, db_path: Path) -> int:
    """Report, and with ``--apply`` perform, deletions inside one root.

    The root must be named. There is no default, because the default would
    eventually be applied to the wrong tree.
    """
    root = config.root(args.root)
    if root is None:
        known = ", ".join(sorted(r.name for r in config.roots))
        print(f"error: unknown root {args.root!r}; known roots: {known}", file=sys.stderr)
        return 2

    conn = open_db(db_path) if args.apply else _read_only(db_path)
    try:
        plan = plan_root(conn, root)

        print(f"root             {root.name} ({root.path})")
        print(f"sounds with dupes{plan.sounds_touched:>6}")
        print(f"files to delete  {plan.files}")
        print(f"bytes to free    {plan.bytes_freed} ({human_bytes(plan.bytes_freed)})")
        print(
            f"sounds skipped   {plan.sounds_skipped} "
            f"(every copy protected, {human_bytes(plan.skipped_bytes)} left in place)"
        )

        if args.plan_out is not None:
            written = write_plan(plan, args.plan_out)
            print(f"plan written     {args.plan_out} ({written} deletions)")

        examples = example_lines(plan, max(args.examples, 0))
        if examples:
            print()
            print("examples")
            for line in examples:
                print(f"  {line}")
        print()

        if not args.apply:
            print("DRY RUN: nothing was deleted. Re-run with --apply to delete.")
            return 0

        if not os.access(root.path, os.W_OK):
            print(
                f"error: {root.path} is not writable; refusing to apply. "
                "A read-only root is read-only on purpose.",
                file=sys.stderr,
            )
            return 1

        result = apply_plan(conn, plan, log=lambda m: print(m, file=sys.stderr))
        for line in result.as_lines():
            print(line)
        for path, message in result.failed[:20]:
            print(f"  failed {path}: {message}", file=sys.stderr)
        return 1 if result.failed else 0
    finally:
        conn.close()


def cmd_stats(args: argparse.Namespace, config: Config, db_path: Path) -> int:
    conn = _read_only(db_path)
    try:
        stats = collect_stats(conn)
    finally:
        conn.close()

    db_size = db_path.stat().st_size if db_path.exists() else 0
    print(f"database           {db_path} ({human_bytes(db_size)})")
    print(f"aliases (paths)    {stats.aliases}")
    print(f"blobs (sounds)     {stats.blobs}")
    print(f"unique bytes       {human_bytes(stats.logical_bytes)}")
    print(f"bytes on disk      {human_bytes(stats.physical_bytes)}")
    print(f"probed blobs       {stats.probed_blobs} ({stats.probe_failures} failed)")
    print(f"peaks cached       {stats.peaks_cached}")
    print(f"total duration     {human_duration(stats.total_duration_s)}")
    print(f"favorites / tags   {stats.favorites} / {stats.tags}")
    print()
    print("per root")
    for root in stats.roots:
        print(
            f"  {root.root:<16} {root.aliases:>6} paths  "
            f"{root.distinct_blobs:>6} blobs  "
            f"{human_bytes(root.bytes_on_disk):>10}"
        )
    print()
    print("per extension")
    for ext, count in stats.extensions:
        print(f"  {ext:<10} {count:>6}")
    print()
    print("per codec")
    for codec, count in stats.codecs:
        print(f"  {codec:<10} {count:>6}")
    return 0


def cmd_peaks(args: argparse.Namespace, config: Config, db_path: Path) -> int:
    conn = open_db(db_path)
    try:
        if args.hash:
            targets = [args.hash]
        else:
            limit = max(args.limit, 0)
            if limit == 0:
                print("give --hash or --limit N", file=sys.stderr)
                return 2
            targets = [
                row["hash"]
                for row in conn.execute(
                    "SELECT b.hash AS hash FROM blob b "
                    "WHERE b.peaks IS NULL "
                    "AND EXISTS (SELECT 1 FROM alias a WHERE a.hash = b.hash) "
                    "LIMIT ?",
                    (limit,),
                )
            ]
        failures = 0
        for digest in targets:
            try:
                blob = ensure_peaks(conn, digest)
            except PeaksError as exc:
                failures += 1
                print(f"{digest[:16]}  failed: {exc}", file=sys.stderr)
                continue
            print(f"{digest[:16]}  {len(blob)} bytes  {len(blob) // 2} buckets")
        print(f"computed {len(targets) - failures} of {len(targets)} ({BUCKETS} buckets each)")
        return 1 if failures and len(targets) == failures else 0
    finally:
        conn.close()


def cmd_silence(args: argparse.Namespace, config: Config, db_path: Path) -> int:
    """Measure dead air, one sound at a time, and store every gap.

    This is what makes the silence tables reproducible rather than a one-off.
    A fresh index, or five hundred newly scanned sounds, are caught up by
    running it again; it skips anything already measured, so it can be stopped
    and restarted at will.

    ffmpeg decodes to the null muxer. No audio file is opened for writing.
    """
    conn = open_db(db_path)
    try:
        targets: list[tuple[str, str, float | None]]
        if args.hash:
            targets = [(str(args.hash), _first_path(conn, args.hash), None)]
        elif args.force:
            rows = conn.execute(
                "SELECT b.hash AS hash, b.duration_s AS duration_s,"
                " (SELECT a.path FROM alias a WHERE a.hash = b.hash ORDER BY a.id"
                "  LIMIT 1) AS path FROM blob b"
                " WHERE EXISTS (SELECT 1 FROM alias a WHERE a.hash = b.hash)"
                " ORDER BY b.hash"
                + (f" LIMIT {int(args.limit)}" if args.limit > 0 else "")
            ).fetchall()
            targets = [(str(r["hash"]), str(r["path"]), r["duration_s"]) for r in rows]
        else:
            targets = silence.unmeasured(
                conn,
                limit=max(args.limit, 0),
                include_discarded=args.include_discarded,
            )

        if not targets:
            print("every sound has been measured")
            return 0

        done = 0
        failures = 0
        intervals = 0
        for digest, path, duration in targets:
            try:
                measurement = silence.measure(Path(path))
            except silence.SilenceError as exc:
                failures += 1
                print(f"{digest[:16]}  failed: {exc}", file=sys.stderr)
                continue
            written = silence.write(
                conn, digest, measurement, at=now_iso(), duration_s=duration
            )
            intervals += written
            done += 1
            if not args.quiet:
                silent = measurement.silent_s
                wall = duration if duration is not None else measurement.duration_s
                share = f"{100.0 * silent / wall:.0f}%" if wall else "  ?"
                print(
                    f"{digest[:16]}  {written:>3} gaps  "
                    f"{human_duration(silent)} silent  {share:>4}"
                )
        print(
            f"measured {done} of {len(targets)} sound(s), {intervals} interval(s)"
            + (f", {failures} failure(s)" if failures else "")
        )
        return 1 if failures and done == 0 else 0
    finally:
        conn.close()


def cmd_projects(args: argparse.Namespace, config: Config, db_path: Path) -> int:
    """Print the board as the files say it is, or rebuild the cache from them."""
    from .projects import model as project_model
    from .projects.store import Caps, ProjectStore

    settings = config.projects or default_projects(db_path.parent)
    try:
        validator = project_model.load_validator(settings.schemas_dir)
    except FileNotFoundError:
        print(
            f"error: no project schema at {settings.schemas_dir}; run "
            "'npm run schema' in frontend/",
            file=sys.stderr,
        )
        return 2
    store = ProjectStore(
        settings.dir,
        validator=validator,
        caps=Caps(
            stored=settings.cap("stored"),
            collage=settings.cap("collage"),
            enrich=settings.cap("enrich"),
        ),
    )
    conn = open_db(db_path)
    try:
        at = project_model.utc_now()
        if args.rebuild:
            count = store.rebuild(conn, at=at)
            print(f"rebuilt the index from {count} file(s) in {settings.dir}")
            return 0
        loaded = store.sync(conn, at=at)
        occupancy = store.occupancy(loaded)
        print(f"{settings.dir}")
        for column in project_model.COLUMNS:
            cap = settings.cap(column)
            count = occupancy[column]
            flag = "  OVER" if project_model.is_over(count, cap) else ""
            print(f"  {column:<8} {count}/{cap}{flag}")
        for item in loaded:
            if not item.valid:
                print(f"  ! {item.id}: {item.problem}", file=sys.stderr)
        print(f"{len(loaded)} project file(s)")
        return 0
    finally:
        conn.close()


def cmd_serve(args: argparse.Namespace, config: Config, db_path: Path) -> int:
    """Start the API. The database must already exist."""
    from .server.app import app_from_config, serve_app
    from .server.database import MissingDatabase

    served = config if db_path == config.db_path else replace(config, db_path=db_path)
    host = args.host or config.server.host
    port = args.port or config.server.port
    try:
        app = app_from_config(served)
    except MissingDatabase as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"database {db_path}")
    print(f"listening on http://{host}:{port}  (docs at /docs)")
    return serve_app(app, host=host, port=port)


def cmd_search(args: argparse.Namespace, config: Config, db_path: Path) -> int:
    conn = _read_only(db_path)
    try:
        rows = conn.execute(
            "SELECT a.path AS path, a.hash AS hash FROM alias_fts f "
            "JOIN alias a ON a.id = f.rowid WHERE alias_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (args.query, args.limit),
        ).fetchall()
        for row in rows:
            print(f"{row['hash'][:16]}  {row['path']}")
        print(f"{len(rows)} match(es)")
    finally:
        conn.close()
    return 0


def cmd_segment(args: argparse.Namespace, config: Config, db_path: Path) -> int:
    """Run one classifier over the collection and store its spans."""
    from .segment.runner import build_segmenter, run_method

    def log(message: str) -> None:
        if not args.quiet:
            print(message, file=sys.stderr, flush=True)

    try:
        segmenter = build_segmenter(args.method)
    except ImportError as exc:
        print(
            f"error: {args.method} needs the optional model dependencies: {exc}\n"
            "install them with: uv sync --extra segment",
            file=sys.stderr,
        )
        return 4

    conn = open_db(db_path)
    try:
        summary = run_method(
            conn,
            segmenter,
            include_discarded=args.include_discarded,
            limit=args.limit or None,
            max_duration_s=args.max_duration or None,
            force=args.force,
            log=log,
        )
    finally:
        conn.close()

    print(f"database {db_path}")
    for line in summary.as_lines():
        print(line)
    for file_hash, message in summary.errors[:20]:
        print(f"  failed {file_hash[:16]}: {message}", file=sys.stderr)
    return 1 if summary.succeeded == 0 and summary.attempted > 0 else 0


def cmd_bakeoff(args: argparse.Namespace, config: Config, db_path: Path) -> int:
    """Print where the classifiers agree and where they do not."""
    from .segment.audioset import LABELS
    from .segment.compare import (
        all_pairs,
        describe_file,
        folder_proxy,
        method_summary,
    )
    from .segment.store import methods_present, run_totals

    conn = _read_only(db_path)
    try:
        methods = list(args.method) if args.method else methods_present(conn)
        if len(methods) < 1:
            print("no method has written a span yet", file=sys.stderr)
            return 1

        print("per method")
        for method in methods:
            summary = method_summary(conn, method)
            totals = run_totals(conn, method)
            audio_min = totals["audio_s"] / 60.0
            per_min = totals["elapsed_s"] / audio_min if audio_min > 0 else 0.0
            print(
                f"  {method:<8} {summary.files:>5} files  "
                f"{summary.spans:>7} spans  "
                f"{summary.spans_per_file:>6.1f} spans/file  "
                f"{human_duration(summary.seconds)} labelled"
            )
            shares = "  ".join(
                f"{label}={summary.per_label_s.get(label, 0.0) / max(summary.seconds, 1e-9):.1%}"
                for label in LABELS
            )
            print(f"           {shares}")
            counts = "  ".join(f"{k}={v}" for k, v in summary.dominant.items())
            print(f"           dominant label per file: {counts}")
            if totals["files"]:
                print(
                    f"           {per_min:.2f} s per audio-minute, "
                    f"peak rss {totals['peak_rss_b'] / (1 << 20):.0f} MiB, "
                    f"{int(totals['files']) - int(totals['ok'])} failures"
                )
        print()

        # The folders the user filed sounds into are the only labels here that
        # no model produced. They are a weak proxy, not ground truth.
        print("agreement with the folder the user filed the sound in")
        for method in methods:
            scores = folder_proxy(conn, method)
            line = "  ".join(
                f"{s.folder}->{s.expected} {s.fraction:.0%} ({s.files} files)"
                for s in scores
            )
            print(f"  {method:<8} {line}")
        print()

        if len(methods) < 2:
            print("only one method present; nothing to compare")
            return 0

        print("pairwise agreement, measured in seconds of audio")
        for pair in all_pairs(conn, methods, worst_n=max(args.examples, 0)):
            print(
                f"  {pair.left} vs {pair.right}: {pair.fraction:.1%} of "
                f"{human_duration(pair.covered_s)} over {pair.files} files "
                f"({human_duration(pair.covered_s - pair.agreed_s)} in dispute)"
            )
            confused = sorted(
                ((v, k) for k, v in pair.confusion.items() if k[0] != k[1]),
                reverse=True,
            )
            for seconds, (left_label, right_label) in confused[:5]:
                print(
                    f"      {left_label:<6} in {pair.left:<8} but "
                    f"{right_label:<6} in {pair.right:<8} "
                    f"{human_duration(seconds)}"
                )
            for item in pair.worst[: args.examples]:
                name = _first_path(conn, item.hash)
                print(
                    f"      {item.hash[:12]}  agree {item.fraction:5.1%}  "
                    f"dispute {human_duration(item.disagreed_s)}  {name}"
                )
                for line in describe_file(conn, item.hash, methods):
                    print(f"    {line}")
            print()
    finally:
        conn.close()
    return 0


def _first_path(conn: sqlite3.Connection, file_hash: str) -> str:
    row = conn.execute(
        "SELECT path FROM alias WHERE hash = ? ORDER BY id LIMIT 1", (file_hash,)
    ).fetchone()
    return Path(str(row["path"])).name if row else "(no path)"


def _read_only(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise sqlite3.OperationalError(
            f"no database at {db_path}; run 'audio-browser scan' first"
        )
    return connect(db_path, read_only=True)


def human_bytes(count: int) -> str:
    """Format a byte count with binary units."""
    value = float(count)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def human_duration(seconds: float) -> str:
    """Format seconds as ``HH:MM:SS``."""
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
