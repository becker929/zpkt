/**
 * The client always calls relative `/api/...` URLs.
 *
 * Real mode (default): a rewrite forwards `/api/*` to the FastAPI server on
 * port 8090. Because the browser only ever talks to port 3100, there is no
 * cross-origin request and the backend needs no CORS configuration.
 *
 * Mock mode (`NEXT_PUBLIC_MOCK=1`): the rewrite is dropped, so the route
 * handlers under `app/api/` serve generated fixtures instead. This lets the
 * interface be developed and driven before the backend exists.
 */
const MOCK = process.env.NEXT_PUBLIC_MOCK === "1";
const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8090";

/**
 * A suffix on the mock build directory.
 *
 * The browser tests run their own mock servers beside any that is already
 * running by hand: one at the default cap, one with the column cap turned down
 * to one, and one with the cap mistyped. `NEXT_PUBLIC_COLUMN_CAP` is inlined at
 * compile time, so they cannot share a build directory, and two `next dev`
 * processes writing into one overwrite each other's chunks — which shows up on
 * the other server as `__webpack_modules__[moduleId] is not a function` and a
 * page served without its styles.
 */
const DIST_TAG = process.env.NEXT_DIST_TAG ?? "";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // `NEXT_PUBLIC_MOCK` is inlined when the code is compiled, so the two modes
  // cannot share one build directory. Separate directories mean switching
  // between them never serves a stale mode.
  distDir: MOCK ? `.next-mock${DIST_TAG ? `-${DIST_TAG}` : ""}` : ".next",
  // The development indicator sits in the bottom-left corner, on top of the
  // player bar. The player bar matters more.
  devIndicators: false,
  // The phone reaches this dev server over Tailscale, so the request for
  // `/_next/*` carries a tailnet address rather than localhost. Naming those
  // hosts here stops Next warning on every page load and keeps the development
  // asset routes working when a future version starts refusing them.
  allowedDevOrigins: ["127.0.0.1", "localhost", "100.120.149.46", "*.ts.net", "192.168.0.106"],
  async rewrites() {
    if (MOCK) return [];
    // `beforeFiles` so the real backend wins over the mock route handlers.
    return {
      beforeFiles: [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }],
      afterFiles: [],
      fallback: [],
    };
  },
};

export default nextConfig;
