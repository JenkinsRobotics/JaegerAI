/**
 * Widget registry (Jenkins Robotics, 2026-10-29, original).
 *
 * A plain array you append to. Adding a widget is additive: no schema change, no
 * migration. Removing one is a breaking change for saved layouts, so a definition
 * removed here must leave its `kind` in RETIRED so hosts can show a clear message
 * instead of a blank card.
 */
import type { AnyWidgetDef, WidgetDef, WidgetSize } from "./types";

const definitions: AnyWidgetDef[] = [];

/** Kinds that existed in a shipped build and must still be recognisable in layouts. */
const RETIRED = new Set<string>();

export function registerWidget<P, D>(def: WidgetDef<P, D>): WidgetDef<P, D> {
  if (definitions.some((d) => d.kind === def.kind) && !RETIRED.has(def.kind)) {
    throw new Error(`widget kind already registered: ${def.kind}`);
  }
  definitions.push(def as unknown as AnyWidgetDef);
  return def;
}

/** Register many at once; used by the barrel so ordering stays explicit. */
export function registerWidgets(defs: AnyWidgetDef[]): void {
  for (const def of defs) registerWidget(def as unknown as WidgetDef<never, unknown>);
}

export function allWidgets(): AnyWidgetDef[] {
  return [...definitions].sort((a, b) => a.title.localeCompare(b.title));
}

export function widgetByKind(kind: string): AnyWidgetDef | undefined {
  return definitions.find((d) => d.kind === kind);
}

export function isRetired(kind: string): boolean {
  return RETIRED.has(kind);
}

/** Widgets a given host can mount, filtered by the size it can offer. */
export function widgetsForHost(host: string, size?: WidgetSize): AnyWidgetDef[] {
  return allWidgets().filter(
    (d) => d.hosts.includes(host as never) && (!size || d.sizes.includes(size)),
  );
}

/** Largest size a widget supports at or below the host's ceiling. */
const ORDER: WidgetSize[] = ["inline", "circle", "rect", "sm", "md", "lg", "xl"];

export function pickSize(supported: WidgetSize[], ceiling: WidgetSize): WidgetSize {
  const limit = ORDER.indexOf(ceiling);
  const usable = supported.filter((s) => ORDER.indexOf(s) <= limit);
  if (!usable.length) return supported[0];
  return usable.reduce((best, s) => (ORDER.indexOf(s) > ORDER.indexOf(best) ? s : best), usable[0]);
}
