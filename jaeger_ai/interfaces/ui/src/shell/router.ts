/**
 * Unified-UI router (Jenkins Robotics, 2026-10-30).
 *
 * One app, one address. Every page of the shell has a real path; the History API
 * keeps deep links, reload and back/forward working. Legacy `?ui=` links (the old
 * three-app switch) are rewritten once, in place, to the matching page. Retired top-level
 * paths from before the 9-tab consolidation are rewritten to their sub-tab (LEGACY_PATHS).
 */
import { useEffect, useState } from "react";

export type PageId = "home" | "chat" | "agents" | "work" | "research" | "studio" | "models" | "machine" | "settings";

/** The nine top-level tabs (2026-10-30 consolidation; 17 → 9). */
export const PAGES: readonly PageId[] = ["home", "chat", "agents", "work", "research", "studio", "models", "machine", "settings"];

/** Sub-tabs of merged pages, in display order; the first is the default. */
export const SUBTABS: Partial<Record<PageId, readonly { id: string; title: string }[]>> = {
  home: [{ id: "overview", title: "Overview" }, { id: "widgets", title: "My widgets" }],
  agents: [{ id: "roster", title: "Agents" }, { id: "characters", title: "Characters" }],
  work: [{ id: "pipeline", title: "Pipeline" }, { id: "tasks", title: "Tasks" }, { id: "production", title: "Production" }, { id: "calendar", title: "Calendar" }],
  research: [{ id: "runs", title: "Research" }, { id: "documents", title: "Documents" }, { id: "knowledge", title: "Memory & Skills" }, { id: "sharepoint", title: "SharePoint" }],
  models: [{ id: "library", title: "Models" }, { id: "compare", title: "Compare" }],
};

/** Every retired top-level path → its new home (path after the page segment is kept). */
export const LEGACY_PATHS: Record<string, string> = {
  characters: "/agents/characters",
  tasks: "/work/tasks",
  calendar: "/work/calendar",
  documents: "/research/documents",
  knowledge: "/research/knowledge",
  sharepoint: "/research/sharepoint",
  compare: "/models/compare",
  integrations: "/settings/integrations",
  workspace: "/home/widgets",
};

export interface Route {
  page: PageId;
  /** Sub-tab id for merged pages (defaults to the first), "" otherwise. */
  sub: string;
  /** Path after the page segment (and after the sub-tab for merged pages), e.g. a settings tab or "gallery". */
  rest: string;
  params: URLSearchParams;
}

export function pathOf(page: PageId, sub?: string): string {
  const base = page === "home" ? "/" : `/${page}`;
  if (!sub || sub === SUBTABS[page]?.[0]?.id) return base;
  return page === "home" ? `/home/${sub}` : `${base}/${sub}`;
}

/** Old top-level paths (/characters, /tasks/gallery?x=1 …) → the new path, or null when already current. */
export function canonicalPath(pathname: string, search = ""): string | null {
  const parts = pathname.replace(/^\/+|\/+$/g, "").split("/").filter(Boolean);
  const target = parts[0] ? LEGACY_PATHS[parts[0]] : undefined;
  if (!target) return null;
  const tail = parts.slice(1).join("/");
  return `${target}${tail ? `/${tail}` : ""}${search}`;
}

/** Parse a location (path + search). Unknown paths fall back to Home; retired paths resolve to their new tab. */
export function parseRoute(pathname: string, search = ""): Route {
  const legacy = canonicalPath(pathname);
  if (legacy) pathname = legacy;
  const params = new URLSearchParams(search);
  const parts = pathname.replace(/^\/+|\/+$/g, "").split("/").filter(Boolean);
  const head = (parts[0] ?? "home") as PageId;
  const known = PAGES.includes(head);
  const page: PageId = known ? head : "home";
  const rest = known ? parts.slice(1) : [];
  const subs = SUBTABS[page];
  if (!subs) return { page, sub: "", rest: rest.join("/"), params };
  const hit = subs.find((s) => s.id === rest[0]);
  return { page, sub: hit ? hit.id : subs[0].id, rest: (hit ? rest.slice(1) : rest).join("/"), params };
}

/** Old `?ui=` / localStorage flags → the page that replaced that app. Returns null when nothing to rewrite. */
export function legacyRedirect(pathname: string, search: string): string | null {
  const params = new URLSearchParams(search);
  const ui = params.get("ui");
  if (ui === null) return null;
  params.delete("ui");
  const target = ui === "apple" ? "/agents/characters" : ui === "windows" ? "/" : "/chat";
  const keep = params.toString();
  const base = pathname === "/" || pathname === "" ? target : pathname;
  return keep ? `${base}?${keep}` : base;
}

/** Retire the old per-app flags so a stale browser can't pin itself to a removed UI. */
export function clearLegacyFlags(storage: Pick<Storage, "removeItem"> | undefined = globalThis.localStorage): void {
  try { storage?.removeItem("jaeger.ui.apple"); storage?.removeItem("jaeger.ui.windows"); } catch { /* private mode */ }
}

const EVENT = "jaeger:navigate";

export function navigate(to: PageId | string, opts: { replace?: boolean } = {}): void {
  let url = (PAGES as readonly string[]).includes(to) ? pathOf(to as PageId) : to;
  const q = url.indexOf("?");
  url = canonicalPath(q < 0 ? url : url.slice(0, q), q < 0 ? "" : url.slice(q)) ?? url;
  if (url === location.pathname + location.search) return;
  if (opts.replace) history.replaceState(null, "", url); else history.pushState(null, "", url);
  dispatchEvent(new Event(EVENT));
}

/** Rewrites a retired path in the address bar (replace, so Back doesn't bounce) and parses it. */
export function currentRoute(): Route {
  const legacy = canonicalPath(location.pathname, location.search);
  if (legacy) history.replaceState(null, "", legacy + location.hash);
  return parseRoute(location.pathname, location.search);
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(currentRoute);
  useEffect(() => {
    const sync = () => setRoute(currentRoute());
    addEventListener("popstate", sync);
    addEventListener(EVENT, sync);
    return () => { removeEventListener("popstate", sync); removeEventListener(EVENT, sync); };
  }, []);
  return route;
}
