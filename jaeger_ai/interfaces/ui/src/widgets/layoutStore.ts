/**
 * Layout store (Jenkins Robotics, 2026-10-29, original).
 *
 * The gateway at ~/.jaeger/dashboard.json is the source of truth once its route
 * exists. The browser cache is the fallback while that route is pending (404) and
 * the read-through copy that avoids an empty first paint; it is always written on
 * save so the operator never loses a placement.
 *
 * Shape is versioned (`v: 1`). Bump `v` and migrate — never change the shape silently.
 */
import type { DashboardDoc, GridItem, WidgetHost } from "./types";

const CACHE_KEY = "jaeger.dashboard.cache.v1";
const DOC_VERSION = 1;

export const emptyDoc = (): DashboardDoc => ({
  v: DOC_VERSION,
  hosts: { page: [], float: [], overlay: [], menubar: [] },
});

/** Coerce unknown JSON into a valid doc. Anything unrecognised is dropped, not guessed. */
export function parseDoc(raw: unknown): DashboardDoc {
  const doc = emptyDoc();
  if (!raw || typeof raw !== "object") return doc;
  const candidate = raw as Partial<DashboardDoc>;
  if (candidate.v !== DOC_VERSION) return doc;
  const hosts = candidate.hosts;
  if (!hosts || typeof hosts !== "object") return doc;
  for (const host of Object.keys(doc.hosts) as WidgetHost[]) {
    const items = (hosts as Record<string, unknown>)[host];
    if (!Array.isArray(items)) continue;
    doc.hosts[host] = items.flatMap((raw): GridItem[] => {
      if (!raw || typeof raw !== "object") return [];
      const g = raw as Partial<GridItem>;
      if (typeof g.i !== "string" || !g.i) return [];
      const num = (value: unknown, fallback: number) =>
        typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.round(value)) : fallback;
      const item: GridItem = { i: g.i, x: num(g.x, 0), y: num(g.y, 0), w: num(g.w, 3), h: num(g.h, 2) };
      // Params pass through verbatim when they are a plain object; anything else is dropped.
      if (g.params && typeof g.params === "object" && !Array.isArray(g.params)) {
        item.params = g.params as Record<string, unknown>;
      }
      return [item];
    });
  }
  return doc;
}

/** Read the browser cache. Only used to avoid an empty first paint. */
export function readCache(): DashboardDoc {
  try {
    return parseDoc(JSON.parse(localStorage.getItem(CACHE_KEY) ?? "null"));
  } catch {
    return emptyDoc();
  }
}

export function writeCache(doc: DashboardDoc): void {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(doc));
  } catch {
    /* storage unavailable — the gateway copy remains authoritative */
  }
}

/** The transport the host must supply. Kept separate so this file stays dependency-free. */
export interface LayoutRead {
  doc: DashboardDoc;
  /** False when the gateway has no dashboard route yet. Not an error. */
  available: boolean;
}

export interface LayoutTransport {
  read(): Promise<LayoutRead>;
  write(doc: DashboardDoc): Promise<void>;
}

/**
 * Load the authoritative document, refreshing the cache on success.
 * When the route is absent the cached copy is returned and `available` is false so the
 * host can say so in plain words — never a raw status code.
 */
export async function loadLayout(transport: LayoutTransport): Promise<{ doc: DashboardDoc; available: boolean }> {
  try {
    const { doc, available } = await transport.read();
    const parsed = parseDoc(doc);
    if (available) {
      writeCache(parsed);
      return { doc: parsed, available };
    }
    // Route absent or write never landed: the browser copy is all we have.
    return { doc: readCache(), available: false };
  } catch {
    return { doc: readCache(), available: false };
  }
}

/**
 * Persist a layout. The browser cache is always updated first so a layout survives
 * even while the gateway route is pending (404); the gateway write is then attempted
 * and only throws when it fails after the local copy already holds the change.
 */
export async function saveLayout(transport: LayoutTransport, doc: DashboardDoc): Promise<void> {
  const next: DashboardDoc = { v: DOC_VERSION, hosts: doc.hosts };
  writeCache(next);
  await transport.write(next);
}

/** Replace one host's items immutably. */
export function withHost(doc: DashboardDoc, host: WidgetHost, items: GridItem[]): DashboardDoc {
  return { v: doc.v, hosts: { ...doc.hosts, [host]: items } };
}

/** Add a widget at the next free row on that host. */
export function addItem(
  doc: DashboardDoc,
  host: WidgetHost,
  item: Omit<GridItem, "y"> & { params?: Record<string, unknown> },
): DashboardDoc {
  const items = doc.hosts[host];
  const y = items.reduce((max, g) => Math.max(max, g.y + g.h), 0);
  return withHost(doc, host, [...items, { ...item, y }]);
}

export function removeItem(doc: DashboardDoc, host: WidgetHost, kind: string): DashboardDoc {
  return withHost(doc, host, doc.hosts[host].filter((g) => g.i !== kind));
}
