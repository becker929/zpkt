import type { Metadata, Viewport } from "next";

import { Shell } from "@/components/Shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "audio browser",
  description: "Browse a hash-indexed personal audio collection.",
  // Filenames here are full of digit runs: `01-banana-pancake_2023-12-05_…`.
  // iOS Safari rewrites runs like that into `tel:` links while it parses the
  // document, which is before React hydrates, and a rewritten tree no longer
  // matches what the server sent. Turning detection off keeps the markup the
  // browser hydrates identical to the markup the server wrote.
  formatDetection: { telephone: false, date: false, address: false, email: false },
  appleWebApp: { capable: true, title: "audio browser", statusBarStyle: "black-translucent" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // The player bar sits on the bottom edge. `cover` lets the page paint into
  // the area behind the home indicator, and the bar pads itself back out of it
  // with `env(safe-area-inset-bottom)`.
  viewportFit: "cover",
  themeColor: "#0e1013",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
