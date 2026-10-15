# Images made with Gemini

Anthony, 14 October 2026: every image generated for this project must be on a gallery page on the tailnet, with its
brief context, the full prompt and the settings used. This is how that is made deterministic.

## The rule

**Every call to an image model goes through `harness.images`** (`lib/harness/src/harness/images.py`). Nothing else
calls the Gemini API for images: no scripts of their own, no curl. The wrapper keeps every image a call returns,
together with its record, before it returns. A call without its context and batch is refused, and calls that make
no image are recorded too.

## Making images

```
cd lib/harness
uv run harness images gen "<prompt>" --context "why, in a sentence" --batch wasteland-styles-2 \
    [--title euro] [--model gemini-3-pro-image] [--aspect 9:16] [--size 2K] [--input ref.png ...]
uv run harness images batch jobs.json --context "..." --batch ... [--parallel 4]
uv run harness images list [--batch ...]
```

- **Jobs file:** a JSON list of `{prompt, title?, aspect?, size?, model?, context?, inputs?}`.
- **Inputs:** reference images, sent before the prompt (for edits and style transfer).
- **Model:** the default is `gemini-3-pro-image`. `uv run harness images list` shows what has been used.
- **Key:** the Keychain's `zpkt-gemini-api-key` (or `HARNESS_GEMINI`).

## Where they are

- **Files:** on this Mac only, never in git, under `HARNESS_IMAGES` (default `~/_agent_scratch/studio/images`):
  - `images.jsonl`: one record per image, append-only. A record holds the id, the time, the batch, the context, the
    title, the full prompt, the model, the settings sent, the reference images, the seconds, the tokens, what the
    model said, the size and the files.
  - `files/<id>.png`: the image as it came.
  - `files/<id>.t.jpg`: the wall's copy, at most 900 px wide.
  - `errors.jsonl`: calls that made no image, and why.
- **The wall:** `/studio/images/` (behind the harness password).
  - Every image, newest first, in a masonry layout, with chips to filter by batch.
  - Each card shows the batch and its brief context, the model and settings, and the full prompt and settings when
    opened. Tap an image to see it whole.
  - Each card has a thumb up and down, which go to the artist's feedback (`docs/artist-agent.md`, view `images`).
  - The page holds only what is near the screen. An image loads as it comes within a screen and a half and is let go
    (its src removed) beyond that. Records arrive a page at a time.

## Game art made from them

A game asset made from a generated image may be committed: cut out, trimmed and resized, compressed (WebP, at most
about 300 KB). Its region's art manifest names the id of the image it came from, so the wall shows its origin. The
generated originals stay on the Mac.
