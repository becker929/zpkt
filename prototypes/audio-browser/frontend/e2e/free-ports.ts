/**
 * The test ports must be free before Playwright starts a server on them.
 *
 * `reuseExistingServer: false` is not enough. Before launching a `webServer`,
 * Playwright probes its URL with an HTTP GET that has no timeout, and it does
 * that before the entry's `timeout` deadline exists. A process that holds the
 * port but never answers HTTP — a wedged `next dev`, or a bare TCP listener —
 * accepts the connection and the probe waits forever. The run then sits with
 * an empty log until somebody kills it; one such run went for three hours.
 *
 * Nothing in Playwright runs before that probe except loading the config
 * file, so this is called from `playwright.config.ts` as it loads. It runs
 * once, in the runner's main process, and asks the kernel who is listening
 * rather than trying to connect: a listener that never answers is exactly the
 * case a connection check cannot tell from a healthy server.
 *
 * The user's own server on 3100 is not a `webServer` entry and is not
 * checked; the live project attaches to it on purpose.
 */

import { execFileSync } from "node:child_process";

/** One process holding a port. */
export interface Holder {
  pid: number;
  command: string;
}

/**
 * The processes listening on `port`, by asking `lsof`.
 *
 * `lsof` exits 1 when nothing matches, which is the answer "free". Any other
 * failure — `lsof` missing, say — is reported as no holders, with a line on
 * stderr, so a machine without `lsof` still runs the suite.
 */
export function holdersOf(port: number): Holder[] {
  let out: string;
  try {
    out = execFileSync("lsof", ["-nP", `-tiTCP:${port}`, "-sTCP:LISTEN"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    });
  } catch (err) {
    const status = (err as { status?: number }).status;
    if (status !== 1) {
      process.stderr.write(`free-ports: could not ask lsof about port ${port}; skipping the check\n`);
    }
    return [];
  }
  return out
    .split("\n")
    .map((line) => Number(line.trim()))
    .filter((pid) => Number.isInteger(pid) && pid > 0)
    .map((pid) => ({ pid, command: commandOf(pid) }));
}

function commandOf(pid: number): string {
  try {
    return execFileSync("ps", ["-o", "command=", "-p", String(pid)], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return "?";
  }
}

/** The failure, in words, for every held port. Empty when all are free. */
export function heldPortLines(ports: readonly number[]): string[] {
  const lines: string[] = [];
  for (const port of ports) {
    for (const holder of holdersOf(port)) {
      lines.push(`port ${port} is held by pid ${holder.pid} (${holder.command}); kill ${holder.pid} and run again`);
    }
  }
  return lines;
}

/**
 * Throw if any of `ports` is held. Once per process.
 *
 * The config file is loaded again in every worker, once the servers are up
 * and holding their ports; workers carry `TEST_WORKER_INDEX` and are skipped.
 * A process that reloads the config with its servers still running (UI mode)
 * is skipped by the flag the first check leaves in the environment.
 */
export function assertPortsFree(ports: readonly number[]): void {
  if (process.env.TEST_WORKER_INDEX !== undefined) return;
  if (process.env.E2E_PORTS_CHECKED === "1") return;
  process.env.E2E_PORTS_CHECKED = "1";
  const lines = heldPortLines(ports);
  if (lines.length === 0) return;
  throw new Error(
    "a test port is not free, so no test server can start on it:\n  " +
      lines.join("\n  ") +
      "\nPlaywright would wait forever on a port that accepts a connection and never answers.",
  );
}
