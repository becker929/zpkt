"use client";

/**
 * A media query as React state.
 *
 * The server has no viewport, so the first render always reports `false` and an
 * effect corrects it after mount. Anything rendered from this value must
 * therefore be something the server is allowed to get wrong: layout that CSS
 * also handles, or content that does not exist yet at hydration time. Never use
 * it to choose an attribute that the server writes into the HTML.
 */

import { useEffect, useState } from "react";

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mql = window.matchMedia(query);
    const sync = () => setMatches(mql.matches);
    sync();
    mql.addEventListener("change", sync);
    return () => mql.removeEventListener("change", sync);
  }, [query]);

  return matches;
}

/** The one breakpoint this interface has. Keep it equal to the value in globals.css. */
export const NARROW = "(max-width: 720px)";
