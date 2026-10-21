#!/usr/bin/env node
// Fails if a vendored token file differs from its pinned sha256 (VENDORED.json) or from the package dist manifest.
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const ui = join(dirname(fileURLToPath(import.meta.url)), "..");
const dir = join(ui, "vendor", "jaeger-design-tokens");
const pin = JSON.parse(readFileSync(join(dir, "VENDORED.json"), "utf8"));
const manifestPath = join(ui, "..", "..", "..", "packages", "jaeger-design-tokens", "dist", "MANIFEST.json");
const manifest = existsSync(manifestPath) ? JSON.parse(readFileSync(manifestPath, "utf8")) : null;
let bad = 0;
for (const [file, sha] of Object.entries(pin.sha256)) {
  const got = createHash("sha256").update(readFileSync(join(dir, file))).digest("hex");
  if (got !== sha) { console.log(`${file}: sha256 ${got} != pinned ${sha}`); bad += 1; }
  if (manifest && manifest.files[file] !== sha) { console.log(`${file}: pin differs from package dist ${manifest.version}`); bad += 1; }
}
if (bad) { console.error(`\nvendored tokens: ${bad} mismatch(es). Re-vendor from packages/jaeger-design-tokens/dist.`); process.exit(1); }
console.log(`vendored-tokens: ok (${pin.package} ${pin.version})`);
