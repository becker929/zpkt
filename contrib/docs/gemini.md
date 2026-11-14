# The Gemini chat

A chat with Gemini that knows zpkt, at `/studio/gemini/` on the Mac's tailnet address, behind the harness password.
It replaces the standalone chat that ran on its own port (`~/gemini-web`, tailnet :8789).

## What it can do

- **Read the repo.** Gemini has four read-only tools: list a folder, read a file, search with a regular expression,
  and read the git log. They see tracked files only (`git ls-files`), so untracked and ignored files, secrets among
  them, are invisible. They read the checkout the harness runs from, on whatever branch it is on. The page shows that
  branch when it is not `main`.
- **Make images.** Its `make_image` tool calls `harness.images`, so every image keeps its record and lands on the wall
  (`/studio/images/?batch=gemini-<chat id>`). The context recorded with each image is the chat's title and what was
  asked. A turn can make at most four images, and Gemini is told to make them only when asked.
- **Hand work to Claude.** Gemini cannot change files, run code or drive Live. Under each reply, **Send to Claude**
  opens a sheet with an editable prompt (the question, the answer, and a request to check Gemini's claims against
  the repo). It then starts a harness job (`/api/rpc` `job`), the same as a job from /skrng. Gemini never starts jobs
  itself.
- **Show what it costs.** Each model call is logged with its tokens and an estimate in dollars. A reply shows its
  model and cost, the list shows each chat's total, and the side panel shows this month's chat and image spend (the
  images from `images.jsonl`, whoever made them). These are estimates at the standard rates in `harness/gemini.py`.
  The bill is on the AI Studio and Cloud Billing pages, because the API key cannot read billing.

Turning off **zpkt tools** in a chat's settings makes it a plain chat, with no tools and no zpkt instructions.

## Where things are

- **Code:** `contrib/harness/src/harness/gemini.py` (chats, tools, the turn loop, the estimate) and
  `contrib/harness/src/harness/studio/gemini_routes.py` (the routes). The page is in
  `contrib/harness/src/harness/studio/static/gemini/`, and the tests are in `contrib/harness/tests/test_gemini.py`.
- **Data:** on the Mac, under `HARNESS_STUDIO/gemini` (default `~/_agent_scratch/studio/gemini`):
  - `chats/<id>.json`: each chat, with its contents as the API takes them. Keys that start with `_` are the page's
    own and are stripped before sending.
  - `files/<id>/`: the chat's attachments. They are inlined when a message is sent, and they live on the Mac, never
    in git.
  - `usage.jsonl`: one line per model call.
  - `settings.json`: the defaults a new chat starts with.
- **Key:** the Keychain's `zpkt-gemini-api-key` (or `HARNESS_GEMINI`), the same key the images use. The browser never
  sees it.

A reply streams to the page as NDJSON events: `chat`, `text`, `tool`, `images`, `usage`, `error`, `done`. The chat
on the Mac is the truth, and the page reloads it after every reply.
