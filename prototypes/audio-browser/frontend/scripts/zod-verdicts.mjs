/**
 * Ask the TypeScript side about a batch of documents, and print its answers.
 *
 * Reads `{ "documents": [...], "collages": [...] }` on stdin and writes
 * `{ "verdicts": [...], "canonical": [...] }` on stdout, each array in the
 * order it was given.
 *
 * Three answers per document. `ok` is `projectDocumentSchema` alone: the part
 * that is emitted to JSON Schema and so the part the two languages have to
 * agree about byte for byte. `checked` is `checkProject`, the schema plus the
 * rules draft 7 cannot carry; those are mirrored by hand in Python's
 * `collage_issues` and friends rather than generated, and `checked` is how the
 * caller confirms the TypeScript side of each mirror actually refuses what it
 * is supposed to.
 *
 * `canonical` is `collageInput` run over each collage: the exact bytes a
 * `collage` commit digests. Python's `collage_input` must produce the same
 * string for the same description, or a commit taken on one side cannot be
 * checked from the other.
 *
 * `scripts/check-schema.py` is the only caller. It exists so that "the two
 * languages accept the same documents and freeze the same bytes" is something
 * that is run rather than something that is believed.
 */

import { checkProject, collageInput, collageSchema, projectDocumentSchema } from "../lib/project.ts";

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const input = JSON.parse(Buffer.concat(chunks).toString("utf8"));

const verdicts = input.documents.map((document) => {
  const parsed = projectDocumentSchema.safeParse(document);
  const checked = checkProject(document);
  return {
    ok: parsed.success,
    issues: parsed.success
      ? []
      : parsed.error.issues.map((issue) => `${issue.path.join(".") || "(root)"}: ${issue.message}`),
    checked: checked.ok,
    checkedIssues: checked.ok ? [] : checked.issues.map((issue) => `${issue.path}: ${issue.message}`),
  };
});

// Each collage is canonicalised twice: as it was written, and again after Zod
// has parsed it, which is where a key left out of the file becomes the default
// on this side. The two must agree with each other and with Python, or a
// description would freeze to different bytes depending on whether it had been
// through a parser — which is exactly how a field added later moves a digest
// taken before it existed.
const canonical = input.collages.map((collage) => {
  const parsed = collageSchema.safeParse(collage);
  return {
    raw: collageInput(collage),
    parsed: parsed.success ? collageInput(parsed.data) : null,
    accepted: parsed.success,
  };
});

process.stdout.write(`${JSON.stringify({ verdicts, canonical })}\n`);
