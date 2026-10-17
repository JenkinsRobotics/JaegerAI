#!/usr/bin/env node
// Production guard: the built bundle must not contain the dev mock adapter
// (review item: "mock code in the production bundle"). Skipped for builds made
// with VITE_JAEGER_MOCK=1, which keep the mock on purpose (screenshots).
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { join } from "node:path";

if (process.env.VITE_JAEGER_MOCK === "1") { console.log("no-mock: skipped (VITE_JAEGER_MOCK=1)"); process.exit(0); }
const dir = join(process.cwd(), "dist", "assets");
if (!existsSync(dir)) { console.error("no-mock: dist/assets missing; run vite build first"); process.exit(1); }
const markers = ["Architect & Notes", "dev mock data", "MOCK_TRANSCRIPTS"];
const hits = readdirSync(dir).filter((f) => f.endsWith(".js")).flatMap((f) => {
  const text = readFileSync(join(dir, f), "utf8");
  return markers.filter((m) => text.includes(m)).map((m) => `${f}: ${m}`);
});
if (hits.length) { console.error(`no-mock: mock data found in the production bundle:\n${hits.join("\n")}`); process.exit(1); }
console.log("no-mock: ok");
