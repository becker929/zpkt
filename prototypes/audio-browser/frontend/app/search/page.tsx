"use client";

/**
 * Search: matches, and nothing else.
 *
 * An empty query shows an empty view. A search box that answers "nothing
 * typed" with the whole collection is a catalogue, and browsing a catalogue is
 * the habit this interface removed: the only way to meet an unheard sound is
 * to swipe it. Typing a name is a different act — you already know which sound
 * you are looking for — so a search reaches every sound, decided or not.
 */

import { Suspense, useEffect } from "react";

import { FileList } from "@/components/FileList";
import { QueryControls } from "@/components/QueryControls";
import { SelectionBar } from "@/components/SelectionBar";
import { useTriage } from "@/components/TriageProvider";
import { filesUrl } from "@/lib/api";
import { PAGE_SIZE, useFiles } from "@/lib/useFiles";
import { useQueryState } from "@/lib/useQueryState";
import { useSelection } from "@/lib/useSelection";
import type { Query } from "@/lib/types";

/**
 * The results, mounted only once something has been typed.
 *
 * Mounting is what starts the fetch, so an empty query costs no request at
 * all rather than one whose answer is thrown away.
 */
function Results({ query, update }: { query: Query; update: (next: Partial<Query>) => void }) {
  const triage = useTriage();
  const files = useFiles(query);
  const selection = useSelection(filesUrl(query, PAGE_SIZE, 0));

  // A discard or a restore changes what a row says about itself.
  useEffect(() => {
    if (triage.version > 0) files.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [triage.version]);

  return (
    <>
      <QueryControls
        query={query}
        update={update}
        total={files.total}
        loading={files.loading}
        placeholder="name of the sound…"
      />
      <FileList
        files={files}
        query={query}
        update={update}
        selection={selection}
        empty={`nothing is called “${query.q}”.`}
      />
      <SelectionBar selection={selection} />
    </>
  );
}

function SearchView() {
  const [query, update] = useQueryState();
  // Every sound is reachable by name, whether it was taken, discarded, or not
  // yet answered. Hiding a discarded sound from a search for its own name
  // would make the discard pile unreachable.
  const searching = { ...query, deleted: "any" as const };

  if (!query.q.trim()) {
    return (
      <>
        <QueryControls
          query={query}
          update={update}
          total={0}
          loading={false}
          placeholder="name of the sound…"
        />
        <div className="notice" data-testid="search-idle">
          type a name. nothing is listed until something is asked for.
        </div>
      </>
    );
  }

  return <Results query={searching} update={update} />;
}

export default function Page() {
  return (
    <Suspense fallback={<div className="notice">loading…</div>}>
      <SearchView />
    </Suspense>
  );
}
