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
  if (key in LANGS) return key as LangId;
  return ALIASES[key];
}

let core: Promise<HighlighterCore> | undefined;
const loaded = new Map<LangId, Promise<void>>();
const cache = new Map<string, string>();
const CACHE_MAX = 200;

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
export async function highlight(code: string, lang: string | undefined): Promise<string | null> {
  const id = resolveLang(lang);
  if (!id) return null;
  const key = `${id}\u0000${code}`;
  const hit = cache.get(key);
  if (hit !== undefined) return hit;
  const h = await highlighter();
  let ready = loaded.get(id);
  if (!ready) { ready = h.loadLanguage(LANGS[id]()); loaded.set(id, ready); }
  await ready;
  const html = h.codeToHtml(code, { lang: id, theme: THEME });
  if (cache.size >= CACHE_MAX) cache.delete(cache.keys().next().value as string);
  cache.set(key, html);
  return html;
}
