/**
 * Browser tests for the audio browser interface.
 *
 * Two projects, because the interface has two jobs that need different data.
 *
 * `mock` runs against mock mode on port 3101. The fixture collection is
 * generated from a fixed seed, so counts, names and duplicate groups are the
 * same on every run. Everything that needs an exact number is tested here. It
 * writes nothing: favourites live in the dev server's memory and disappear when
 * it stops.
 *
 * `live` runs against the real stack already listening on port 3100, backed by
 * the real index. It checks the handful of facts that only real data can show,
 * such as a sound stored 30 times inside Logic project bundles. It only reads;
 * no test in it writes to the index.
 *
 * `mobile` runs against the same mock server under an iPhone device
 * descriptor, which means WebKit at 393 by 852 with touch and a device pixel
 * ratio of 3. A narrow desktop window is not the same browser and would not
 * have shown the bottom bar disappearing under the iOS toolbar.
 *
 * Run all three with `npm run test:e2e`. First time on a machine, run
 * `npm run test:e2e:install` to fetch the browsers.
 */

import { defineConfig, devices } from "@playwright/test";

const MOCK_PORT = Number(process.env.E2E_MOCK_PORT ?? 3101);
const LIVE_URL = process.env.E2E_LIVE_URL ?? "http://127.0.0.1:3100";

/**
 * A second mock server, built with the column cap turned down to one.
 *
 * The cap is meant to be turned down, so "sensible at 1" is checked by running
 * the real interface at 1 rather than by reasoning about it. The cap is inlined
 * when the code is compiled, so this needs its own build directory as well as
 * its own port.
 */
const CAP1_PORT = Number(process.env.E2E_CAP1_PORT ?? 3102);

/**
 * A third mock server, built with the cap set to something that is not a cap.
 *
 * A mistyped cap must not quietly loosen the board. What it does instead —
 * refuse the value, run at the tightest setting, and say so on every view — is
 * checked by running the interface that way rather than by reasoning about it,
 * because the whole point of the decision is what somebody sees.
 */
const CAPBAD_PORT = Number(process.env.E2E_CAPBAD_PORT ?? 3103);

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  // The list view fetches pages as it scrolls and the real index answers from a
  // 3,451-row table, so give actions room without hiding a genuine stall.
  timeout: 60_000,
  expect: { timeout: 15_000 },

  projects: [
    {
      name: "mock",
      testMatch: /.*\.mock\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        baseURL: `http://127.0.0.1:${MOCK_PORT}`,
      },
    },
    {
      name: "live",
      testMatch: /.*\.live\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        baseURL: LIVE_URL,
      },
    },
    {
      name: "mobile",
      testMatch: /.*\.mobile\.spec\.ts/,
      use: {
        // The descriptor carries WebKit, touch, the device pixel ratio and the
        // Safari user agent, not only a viewport size.
        ...devices["iPhone 14 Pro"],
        baseURL: `http://127.0.0.1:${MOCK_PORT}`,
      },
    },
    {
      name: "cap1",
      testMatch: /.*\.cap1\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        baseURL: `http://127.0.0.1:${CAP1_PORT}`,
      },
    },
    {
      name: "capbad",
      testMatch: /.*\.capbad\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        baseURL: `http://127.0.0.1:${CAPBAD_PORT}`,
      },
    },
  ],

  // The two mock servers are started here. The live stack is the pair of tmux
  // sessions that serve the real collection; starting a second copy of it would
  // open a second writer on the index.
  webServer: [
    {
      // Its own build directory, and not the one a mock server started by hand
      // is using. `next dev` writes into `distDir` as it compiles, so two
      // processes sharing one directory overwrite each other's chunks: the
      // symptom is `__webpack_modules__[moduleId] is not a function` on the
      // other server, and a page that renders without its styles until the
      // directory is deleted. The tests must not be able to do that to a
      // running session.
      command: `npx next dev -p ${MOCK_PORT}`,
      env: { NEXT_PUBLIC_MOCK: "1", NEXT_DIST_TAG: "e2e" },
      url: `http://127.0.0.1:${MOCK_PORT}/`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      command: `npx next dev -p ${CAP1_PORT}`,
      env: { NEXT_PUBLIC_MOCK: "1", NEXT_PUBLIC_COLUMN_CAP: "1", NEXT_DIST_TAG: "cap1" },
      url: `http://127.0.0.1:${CAP1_PORT}/`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      // "two" is a cap somebody meant to type as 2. It is not a number of
      // slots, so the board runs at its tightest and says so.
      command: `npx next dev -p ${CAPBAD_PORT}`,
      env: { NEXT_PUBLIC_MOCK: "1", NEXT_PUBLIC_COLUMN_CAP: "two", NEXT_DIST_TAG: "capbad" },
      url: `http://127.0.0.1:${CAPBAD_PORT}/`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      stdout: "ignore",
      stderr: "pipe",
    },
  ],
});
