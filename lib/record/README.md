# lib/record

What the system keeps, outside git.

- `fetch_models.sh` — downloads the models ears needs from R2 (private
  `models/` prefix), verifies their SHA-256, and prints `EARS_DCLAP_MODEL`.
- `publish_render.sh` — uploads an approved MP3 to R2 for
  anthonybecker.me/skrng and prints its manifest entry.

Both need a wrangler login with access to the `anthonybecker-audio` bucket.
