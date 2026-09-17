/**
 * Ask Zod about a list of documents, and print one verdict per document.
 *
 * Reads a JSON array of candidate project documents on stdin and writes a JSON
 * array of `{ ok, issues }` on stdout, one entry per input, in the same order.
 *
 * Only `projectDocumentSchema` is applied here, not `checkProject`. The schema
 * is the part that is emitted to JSON Schema and so the part the two languages
 * have to agree about; the extra rules in `checkProject` cannot be written in
 * draft 7 and are mirrored in Python instead of being generated.
 *
 * `scripts/check-schema.py` is the only caller. It exists so that "Zod and the
 * generated JSON Schema accept exactly the same documents" is something that is
 * run rather than something that is believed.
 */

import { projectDocumentSchema } from "../lib/project.ts";

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const cases = JSON.parse(Buffer.concat(chunks).toString("utf8"));

const verdicts = cases.map((document) => {
  const parsed = projectDocumentSchema.safeParse(document);
  return {
    ok: parsed.success,
    issues: parsed.success
      ? []
      : parsed.error.issues.map((issue) => `${issue.path.join(".") || "(root)"}: ${issue.message}`),
  };
});

process.stdout.write(`${JSON.stringify(verdicts)}\n`);
