/**
 * Unified-UI router (Jenkins Robotics, 2026-10-30).
 *
 * One app, one address. Every page of the shell has a real path; the History API
 * keeps deep links, reload and back/forward working. Legacy `?ui=` links (the old
 * three-app switch) are rewritten once, in place, to the matching page.
 */
import { useEffect, useState } from "react";

export type PageId = "home" | "chat" | "agents" | "characters" | "tasks" | "machine" | "sharepoint" | "settings" | "workspace" | "studio";

export const PAGES: readonly PageId[] = ["home", "chat", "agents", "characters", "tasks", "machine", "sharepoint", "settings", "workspace", "studio"];

export interface Route { page: PageId; /** Path after the page segment, e.g. a settings tab or agent id. */ rest: string; params: URLSearchParams }

export function pathOf(page: PageId): string { return page === "home" ? "/" : `/${page}`; }

/** Parse a location (path + search). Unknown paths fall back to Home. */
export function parseRoute(pathname: string, search = ""): Route {
  const params = new URLSearchParams(search);
  const parts = pathname.replace(/^\/+|\/+$/g, "").split("/").filter(Boolean);
  const head = (parts[0] ?? "home") as PageId;
  const page: PageId = PAGES.includes(head) ? head : "home";
  return { page, rest: page === head ? parts.slice(1).join("/") : "", params };
}

/** Old `?ui=` / localStorage flags → the page that replaced that app. Returns null when nothing to rewrite. */
export function legacyRedirect(pathname: string, search: string): string | null {
  const params = new URLSearchParams(search);
  const ui = params.get("ui");
  if (ui === null) return null;
  params.delete("ui");
  const target = ui === "apple" ? "/characters" : ui === "windows" ? "/" : "/chat";
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
  const url = (PAGES as readonly string[]).includes(to) ? pathOf(to as PageId) : to;
  if (url === location.pathname + location.search) return;
  if (opts.replace) history.replaceState(null, "", url); else history.pushState(null, "", url);
  dispatchEvent(new Event(EVENT));
}

export function currentRoute(): Route { return parseRoute(location.pathname, location.search); }

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
