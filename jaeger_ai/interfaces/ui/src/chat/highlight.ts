/* Lazy syntax highlighting (Jenkins Robotics, 2026-10-17, original). Shiki's fine-grained core with the
 * JavaScript regex engine (no WASM), a small language set loaded on first use, and a CSS-variables theme so
 * colors come from chat.css (light/dark) instead of a bundled theme. Nothing loads until a closed fence in a
 * supported language is shown. */
import type { HighlighterCore } from "shiki/core";

const LANGS = {
  typescript: () => import("shiki/langs/typescript.mjs"),
  tsx: () => import("shiki/langs/tsx.mjs"),
  javascript: () => import("shiki/langs/javascript.mjs"),
  jsx: () => import("shiki/langs/jsx.mjs"),
  json: () => import("shiki/langs/json.mjs"),
  shellscript: () => import("shiki/langs/shellscript.mjs"),
  python: () => import("shiki/langs/python.mjs"),
  swift: () => import("shiki/langs/swift.mjs"),
  css: () => import("shiki/langs/css.mjs"),
  html: () => import("shiki/langs/html.mjs"),
  yaml: () => import("shiki/langs/yaml.mjs"),
  toml: () => import("shiki/langs/toml.mjs"),
  diff: () => import("shiki/langs/diff.mjs"),
  sql: () => import("shiki/langs/sql.mjs"),
  markdown: () => import("shiki/langs/markdown.mjs"),
} as const;
type LangId = keyof typeof LANGS;

const ALIASES: Record<string, LangId> = {
  ts: "typescript", mts: "typescript", cts: "typescript", js: "javascript", mjs: "javascript", cjs: "javascript",
  sh: "shellscript", bash: "shellscript", zsh: "shellscript", shell: "shellscript", console: "shellscript",
  py: "python", yml: "yaml", md: "markdown", jsonc: "json", json5: "json", patch: "diff", htm: "html",
};

export const THEME = "jaeger-css-vars";

export function resolveLang(lang: string | undefined): LangId | undefined {
  const key = (lang ?? "").trim().toLowerCase().split(/\s+/)[0];
  if (!key) return undefined;
  if (Object.hasOwn(LANGS, key)) return key as LangId;
  return Object.hasOwn(ALIASES, key) ? ALIASES[key] : undefined;
}

let core: Promise<HighlighterCore> | undefined;
const loaded = new Map<LangId, Promise<void>>();
const cache = new Map<string, string>();
const CACHE_MAX = 64;
const CACHE_UNITS = 1024 * 1024; // UTF-16 code + rendered HTML units, not entry count alone.
let cacheUnits = 0;
export const CODE_UNITS_MAX = 32768;
export const CODE_LINE_MAX = 4096;
const inflight = new Map<string, Promise<string | null>>();
export function highlightCacheUsage() { return {entries: cache.size, units: cacheUnits, budget: CACHE_UNITS, pending: inflight.size}; }
export function clearHighlightCache() { cache.clear(); cacheUnits = 0; }
function remember(key: string, html: string) {
  const units = key.length + html.length;
  if (units > CACHE_UNITS) return;
  while (cache.size >= CACHE_MAX || cacheUnits + units > CACHE_UNITS) {
    const oldest = cache.keys().next().value!;
    cacheUnits -= oldest.length + cache.get(oldest)!.length; cache.delete(oldest);
  }
  cache.set(key, html); cacheUnits += units;
}

function highlighter(): Promise<HighlighterCore> {
  core ??= (async () => {
    const [{ createHighlighterCore, createCssVariablesTheme }, { createJavaScriptRegexEngine }] = await Promise.all([
      import("shiki/core"), import("shiki/engine/javascript"),
    ]);
    return createHighlighterCore({
      themes: [createCssVariablesTheme({ name: THEME, variablePrefix: "--shiki-", fontStyle: true })],
      langs: [],
      engine: createJavaScriptRegexEngine(),
    });
  })();
  return core;
}

/** HTML for a finished code block, or null when the language is not in the set. */
export async function highlight(code: string, lang: string | undefined, signal?: AbortSignal): Promise<string | null> {
  const id = resolveLang(lang);
  // Bound regex-parser input BEFORE loading any grammar. Huge/minified blocks
  // stay plain, retain full source and remain copyable through the caller.
  if (signal?.aborted || !id || code.length > CODE_UNITS_MAX || code.split("\n").some(line => line.length > CODE_LINE_MAX)) return null;
  const key = `${id}\u0000${code}`;
  const hit = cache.get(key);
  if (hit !== undefined) return hit;
  const prior = inflight.get(key);
  if (prior) return prior;
  if (inflight.size >= 4) return null; // Plain fallback, never an unbounded parser queue.
  const job = (async () => {
    const h = await highlighter();
    if (signal?.aborted) return null;
    let ready = loaded.get(id);
    if (!ready) {
      ready = h.loadLanguage(LANGS[id]()); loaded.set(id, ready);
      void ready.catch(() => { if (loaded.get(id) === ready) loaded.delete(id); });
    }
    await ready;
    if (signal?.aborted) return null;
    const html = h.codeToHtml(code, { lang: id, theme: THEME });
    remember(key, html);
    return html;
  })();
  inflight.set(key, job);
  try { return await job; } finally { if (inflight.get(key) === job) inflight.delete(key); }
}
