"use client";

/**
 * Duplicates view: sounds stored at more than one path inside a single root.
 *
 * This view exists to be looked at. It removes nothing and offers nothing to
 * remove: which copy to keep is decided by ear, by hand. What it can do is
 * avoid pointing at bytes that must never go.
 *
 * Copies inside a Logic project bundle are hidden by default. They are the
 * project's own media: the project reads the file from that exact path, and the
 * projects in this collection exist only in the read-only originals, so
 * deleting one corrupts a project permanently. Showing them under a heading
 * that says "wasted" would be an invitation to do exactly that. The count of
 * what is hidden is still reported, and the "show" toggle marks every one of
 * those paths as not deletable.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { fetchDupes, fetchStats } from "@/lib/api";
import { formatBytes, formatCount } from "@/lib/format";
import type { DupePage, Stats } from "@/lib/types";

const LIMIT = 200;

export default function DupesPage() {
  const [page, setPage] = useState<DupePage | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showBundles, setShowBundles] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setPage(null);
    fetchDupes(LIMIT, { includeBundles: showBundles }, controller.signal)
      .then(setPage)
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : String(err));
      });
    return () => controller.abort();
  }, [showBundles]);

  useEffect(() => {
    const controller = new AbortController();
    fetchStats(controller.signal)
      .then(setStats)
      .catch(() => setStats(null));
    return () => controller.abort();
  }, []);

  if (error) return <div className="error">could not load duplicates: {error}</div>;
  if (!page) return <div className="notice">loading…</div>;

  return (
    <div className="detail" data-testid="dupes" data-include-bundles={showBundles}>
      <h1>duplicates</h1>
      <p className="lede">
        A sound is its bytes. Every path in a group below points at the same bytes. Nothing here is
        deleted for you; this view only shows where the repetition is.
      </p>

      {stats ? (
        <div className="panel">
          <div className="stat-row">
            <div className="stat">
              <div className="k">unique sounds</div>
              <div className="v mono">{formatCount(stats.files)}</div>
            </div>
            <div className="stat">
              <div className="k">paths</div>
              <div className="v mono">{formatCount(stats.aliases)}</div>
            </div>
            <div className="stat">
              <div className="k">groups shown</div>
              <div className="v mono" data-testid="dupe-total">
                {formatCount(page.total)}
              </div>
            </div>
            <div className="stat">
              <div className="k">{showBundles ? "space in extra copies" : "space a cleanup could free"}</div>
              <div className="v mono" data-testid="dupe-wasted">
                {formatBytes(page.wasted_bytes)}
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {page.excluded_bundle_groups > 0 ? (
        <div className="panel bundle-guard" data-testid="bundle-guard">
          <p>
            {formatCount(page.excluded_bundle_groups)} more groups, holding{" "}
            {formatBytes(page.excluded_bundle_bytes)}, are not listed. Every copy in them sits inside
            a Logic project bundle. That audio is the project&rsquo;s own media, the projects exist
            only in the read-only originals, and deleting one file corrupts the project that reads
            it. None of it is reclaimable.
          </p>
          <button type="button" className="chip" data-testid="show-bundles" onClick={() => setShowBundles(true)}>
            show them anyway, marked as not deletable
          </button>
        </div>
      ) : null}

      {showBundles ? (
        <div className="panel bundle-guard" data-testid="bundle-warning">
          <p>
            Showing copies inside Logic project bundles. They are marked{" "}
            <span className="locked">in a project</span> and must not be deleted.
          </p>
          <button type="button" className="chip" data-testid="hide-bundles" onClick={() => setShowBundles(false)}>
            back to what a cleanup could free
          </button>
        </div>
      ) : null}

      <div className="panel">
        <h2>worst {page.items.length} by space in extra copies</h2>
        {page.items.length === 0 ? <div className="notice">nothing to show.</div> : null}
        {page.items.map((group) => (
          <div key={group.hash} style={{ marginBottom: 14 }} data-testid="dupe-group" data-hash={group.hash}>
            <div>
              <Link href={`/sounds/${group.hash}`}>{group.filename}</Link>{" "}
              <span className="alias-badge">{group.alias_count} copies</span>{" "}
              <span className="hash mono">
                {formatBytes(group.size_bytes)} each · {formatBytes(group.wasted_bytes)} in extra copies
              </span>
              {group.bundle_copies > 0 ? (
                <span className="locked" data-testid="group-locked">
                  {group.bundle_copies} inside a project — not deletable
                </span>
              ) : null}
            </div>
            <ul className="alias-list">
              {group.entries.map((entry, i) => (
                <li key={entry.path} data-testid="dupe-path" data-deletable={entry.deletable}>
                  <span className="n mono">{i + 1}</span>
                  <span className="path mono">{entry.path}</span>
                  {entry.in_bundle ? (
                    <span className="locked" data-testid="path-locked" title="inside a Logic project bundle">
                      in a project
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
