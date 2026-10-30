#!/usr/bin/env node
// Modified from AetherStudio dev/check-theme-literals.mjs (Apache-2.0, ece0209).
// Theme guard: app CSS must express color through --aether-* tokens.
// Raw color literals are allowed ONLY in custom-property declarations
// (--name: …) or on a line marked /* literal-ok */. Scope: src/**/*.css.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "src");
const colorPattern = /#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/;
const walk = (dir) => readdirSync(dir).flatMap((name) => {
  const path = join(dir, name);
  if (statSync(path).isDirectory()) return walk(path);
  if (!name.endsWith(".css")) return [];
  // Apple-Native UI and Grok-style Windows UI use self-contained system tokens and custom CSS.
  if (path.includes("/theme/apple-") || path.includes("/theme/aether-modern") || path.includes("/theme/modern") || path.includes("/windows/")) return [];
  return [path];
});
let violations = 0;
for (const path of walk(root)) {
  readFileSync(path, "utf8").split("\n").forEach((line, index) => {
    const trimmed = line.trim().replace(/var\([^)]*\)/g, "var()");
    if (!colorPattern.test(trimmed)) return;
    if (trimmed.startsWith("--")) return;
    if (trimmed.includes("literal-ok")) return;
    violations += 1;
    console.log(`${path}:${index + 1}: ${trimmed}`);
  });
}
if (violations) {
  console.error(`\n${violations} raw color literal(s): route them through --aether-* tokens.`);
  process.exit(1);
}
console.log("theme-literals: ok");
