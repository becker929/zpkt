/**
 * Ask Zod about a list of documents, and print one verdict per document.
 *
 * Reads a JSON array of candidate project documents on stdin and writes a JSON
 * array of `{ ok, issues }` on stdout, one entry per input, in the same order.
 *
 * Two verdicts per document. `ok` is `projectDocumentSchema` alone: the part
 * that is emitted to JSON Schema and so the part the two languages have to
 * agree about byte for byte. `checked` is `checkProject`, the schema plus the
 * rules draft 7 cannot carry; those are mirrored by hand in Python's
 * `collage_issues` and friends rather than generated, and `checked` is how the
 * caller confirms the TypeScript side of each mirror actually refuses what it
 * is supposed to.
 *
 * `scripts/check-schema.py` is the only caller. It exists so that "Zod and the
 * generated JSON Schema accept exactly the same documents" is something that is
 * run rather than something that is believed.
 */

import { checkProject, projectDocumentSchema } from "../lib/project.ts";

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const cases = JSON.parse(Buffer.concat(chunks).toString("utf8"));

const verdicts = cases.map((document) => {
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

process.stdout.write(`${JSON.stringify(verdicts)}\n`);
