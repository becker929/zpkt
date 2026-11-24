// A small JSON Schema check for the tests: enough of draft 2020-12 for the booth's generated schemas
// (fixtures/booth-*.schema.json) so the fake booth is held to the real booth's answers without a dependency.
// Keywords: type, enum, const, anyOf, $ref (#/$defs/...), properties, required, additionalProperties, items,
// minLength, maxLength, pattern, minimum, maximum. Any other keyword is refused, so a schema that grows one fails
// loudly here instead of passing unchecked.

const KNOWN = new Set(['$schema', '$id', '$defs', 'title', 'description', 'default', 'type', 'enum', 'const', 'anyOf', '$ref',
  'properties', 'required', 'additionalProperties', 'items', 'minLength', 'maxLength', 'pattern', 'minimum', 'maximum']);

const typeOf = (v) => (v === null ? 'null' : Array.isArray(v) ? 'array' : Number.isInteger(v) ? 'integer' : typeof v);
const isType = (v, t) => typeOf(v) === t || (t === 'number' && typeOf(v) === 'integer');

/** The problems with `value` against `schema` (an empty list when it fits), each "path: what". */
export function schemaProblems(schema, value, root = schema, path = '$') {
  const out = [];
  const bad = (what) => out.push(`${path}: ${what}`);
  for (const k of Object.keys(schema)) if (!KNOWN.has(k)) throw new Error(`schema-check.mjs does not know the keyword ${k} (at ${path})`);
  if (schema.$ref) {
    const m = /^#\/\$defs\/(.+)$/.exec(schema.$ref);
    if (!m || !root.$defs?.[m[1]]) throw new Error(`unresolved $ref ${schema.$ref}`);
    out.push(...schemaProblems(root.$defs[m[1]], value, root, path));
  }
  if (schema.anyOf && !schema.anyOf.some((s) => !schemaProblems(s, value, root, path).length)) bad(`fits none of anyOf (${JSON.stringify(value)?.slice(0, 80)})`);
  if (schema.type && ![schema.type].flat().some((t) => isType(value, t))) { bad(`is ${typeOf(value)}, not ${schema.type}`); return out; }
  if (schema.enum && !schema.enum.some((e) => e === value)) bad(`${JSON.stringify(value)} is not one of ${schema.enum.join(', ')}`);
  if ('const' in schema && schema.const !== value) bad(`is not ${JSON.stringify(schema.const)}`);
  if (typeof value === 'string') {
    if (schema.minLength !== undefined && value.length < schema.minLength) bad(`shorter than ${schema.minLength}`);
    if (schema.maxLength !== undefined && value.length > schema.maxLength) bad(`longer than ${schema.maxLength}`);
    if (schema.pattern && !new RegExp(schema.pattern, 'u').test(value)) bad(`does not match ${schema.pattern}`);
  }
  if (typeof value === 'number') {
    if (schema.minimum !== undefined && value < schema.minimum) bad(`under ${schema.minimum}`);
    if (schema.maximum !== undefined && value > schema.maximum) bad(`over ${schema.maximum}`);
  }
  if (Array.isArray(value) && schema.items) value.forEach((v, i) => out.push(...schemaProblems(schema.items, v, root, `${path}[${i}]`)));
  if (typeOf(value) === 'object') {
    for (const k of schema.required ?? []) if (!(k in value)) bad(`has no ${k}`);
    for (const [k, v] of Object.entries(value)) {
      const sub = schema.properties?.[k];
      if (sub) out.push(...schemaProblems(sub, v, root, `${path}.${k}`));
      else if (schema.additionalProperties === false) bad(`has ${k}, which the schema does not`);
      else if (typeof schema.additionalProperties === 'object') out.push(...schemaProblems(schema.additionalProperties, v, root, `${path}.${k}`));
    }
  }
  return out;
}
