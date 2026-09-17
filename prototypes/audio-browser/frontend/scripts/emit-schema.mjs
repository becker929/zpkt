/**
 * Emit JSON Schema from the Zod definitions in `lib/project.ts`.
 *
 * Zod is the source of truth. This script is the only way the JSON Schema files
 * are written, so the two languages cannot drift: run `npm run schema` after any
 * change to the model and commit what it produces.
 *
 * Run with `node scripts/emit-schema.mjs` from `frontend/`. Node strips the
 * types out of the imported `.ts` module on the way in, so there is no build
 * step and no second copy of the model compiled somewhere.
 *
 * The generated files are self-contained: every `$ref` points inside the same
 * document, so `jsonschema` in Python needs no resolver and no network.
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { zodToJsonSchema } from "zod-to-json-schema";

import { boardSchema, projectDocumentSchema, projectSummarySchema } from "../lib/project.ts";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = join(here, "..", "..", "schemas");

const BASE = "https://audio-browser.local/schemas";

/** One file, one root schema. `$refStrategy: "root"` keeps refs inside it. */
function emit(fileName, schema, id, title, description) {
  const json = zodToJsonSchema(schema, {
    target: "jsonSchema7",
    $refStrategy: "root",
    definitionPath: "$defs",
    errorMessages: false,
  });

  const document = {
    $schema: "http://json-schema.org/draft-07/schema#",
    $id: `${BASE}/${fileName}`,
    title,
    description,
    ...json,
  };

  const path = join(outDir, fileName);
  writeFileSync(path, `${JSON.stringify(document, null, 2)}\n`, "utf8");
  return path;
}

mkdirSync(outDir, { recursive: true });

const written = [
  emit(
    "project.schema.json",
    projectDocumentSchema,
    "project",
    "Project document",
    [
      "One project, as it is stored in audio-browser/projects/<id>.json. The file is the truth;",
      "the SQLite index is a cache that can be rebuilt from the directory.",
      "",
      "Generated from frontend/lib/project.ts by frontend/scripts/emit-schema.mjs. Do not edit.",
      "",
      "The four branches below tie `column` to `commits`: the chain is exactly the stages already",
      "passed, in board order, so a project in `collage` always carries a `stored` commit and its",
      "sound set is frozen as a property of the format.",
      "",
      "Two rules cannot be written in draft 7 and must be checked separately after validation, by",
      "`checkProject` in TypeScript and by its mirror in Python: (1) `sounds` is a set, so no hash",
      "may appear twice; (2) `updated_at` is not before `created_at`, and each commit instant is",
      "not before the one above it.",
    ].join("\n"),
  ),
  emit(
    "project-summary.schema.json",
    projectSummarySchema,
    "project-summary",
    "Project summary",
    [
      "One row of GET /api/projects: enough to draw a board card without opening the file.",
      "",
      "Generated from frontend/lib/project.ts by frontend/scripts/emit-schema.mjs. Do not edit.",
      "",
      "Every measure is nullable. Absent is null and never zero: a length of 0:00 against a project",
      "holding four minutes of audio is a lie, so the interface says nothing instead.",
    ].join("\n"),
  ),
  emit(
    "board.schema.json",
    boardSchema,
    "board",
    "Board",
    [
      "GET /api/board: the columns the server serves, with their caps and occupancy, plus the counts that sit",
      "off the board.",
      "",
      "Generated from frontend/lib/project.ts by frontend/scripts/emit-schema.mjs. Do not edit.",
      "",
      "`over` is the server's reading of its own cap. The client draws what the server reports and",
      "never decides for itself what counts as over.",
    ].join("\n"),
  ),
];

for (const path of written) process.stdout.write(`wrote ${path}\n`);
