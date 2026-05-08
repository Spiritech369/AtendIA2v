#!/usr/bin/env node
/**
 * Generate TypeScript types from the shared `contracts/*.schema.json`.
 * Run via `pnpm types`. Should be invoked any time a schema file changes
 * AND committed (output is checked in so CI doesn't need the generator).
 *
 * Layout assumption:
 *   <repo>/
 *     contracts/*.schema.json           (source of truth)
 *     frontend/scripts/generate-types.mjs   (this file)
 *     frontend/src/types/generated/*.ts (output, .gitignore-d? no — committed)
 */
import { compileFromFile } from "json-schema-to-typescript";
import { mkdir, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(__dirname, "../../contracts");
const DST = path.resolve(__dirname, "../src/types/generated");

await mkdir(DST, { recursive: true });

const entries = await readdir(SRC);
const schemas = entries.filter((f) => f.endsWith(".schema.json"));

if (schemas.length === 0) {
  console.error(`no schemas found under ${SRC}`);
  process.exit(1);
}

const banner =
  "// AUTO-GENERATED — do not edit. Run `pnpm types` to regenerate.\n" +
  "// Source: contracts/*.schema.json\n";

for (const file of schemas) {
  const ts = await compileFromFile(path.join(SRC, file), {
    bannerComment: banner,
    style: { semi: true, singleQuote: false, trailingComma: "all" },
  });
  const outName = file.replace(".schema.json", ".ts");
  const outPath = path.join(DST, outName);
  await writeFile(outPath, ts);
  console.log(`✓ ${file} → src/types/generated/${outName}`);
}

// Re-export everything from a barrel so consumers can `import { Message } from "@/types"`.
const indexLines = schemas
  .map((f) => f.replace(".schema.json", ""))
  .map((name) => `export * from "./${name}";`);
await writeFile(
  path.join(DST, "index.ts"),
  `${banner}\n${indexLines.join("\n")}\n`,
);
console.log(`✓ generated barrel index.ts`);
