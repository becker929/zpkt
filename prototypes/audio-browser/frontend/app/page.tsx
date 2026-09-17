"use client";

/** List view: the whole collection, filtered, sorted, virtualised, and triaged. */

import { Suspense, useEffect } from "react";

import { FileList } from "@/components/FileList";
import { QueryControls } from "@/components/QueryControls";
import { SelectionBar } from "@/components/SelectionBar";
import { usePlayer } from "@/components/PlayerProvider";
import { useTriage } from "@/components/TriageProvider";
import { filesUrl } from "@/lib/api";
import { PAGE_SIZE, useFiles } from "@/lib/useFiles";
import { useQueryState } from "@/lib/useQueryState";
import { useSelection } from "@/lib/useSelection";

function ListView() {
  const [query, update] = useQueryState();
  const player = usePlayer();
  const triage = useTriage();
  const files = useFiles(query, player.favoriteOverrides);

  // The selection belongs to one filtered set. The URL the list is fetching is
  // exactly that set's identity, so changing any filter drops the selection.
  const selection = useSelection(filesUrl(query, PAGE_SIZE, 0));

  // A favourite changed, so the "favorites only" filter may now match a
  // different set. Re-fetch rather than guess.
  useEffect(() => {
    if (player.favoriteVersion > 0 && query.favorite) files.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [player.favoriteVersion]);

  // A discard or a restore changes what this filter selects. Re-fetch the pages
  // on screen: the discarded sound goes, and the rows below it move up.
  useEffect(() => {
    if (triage.version > 0) files.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [triage.version]);

  return (
    <>
      <QueryControls query={query} update={update} total={files.total} loading={files.loading} />
      <FileList files={files} query={query} update={update} selection={selection} />
      <SelectionBar selection={selection} mode={query.deleted === "true" ? "deleted" : "default"} />
    </>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<div className="notice">loading…</div>}>
      <ListView />
    </Suspense>
  );
}
