/**
 * Widget contract (Jenkins Robotics, 2026-10-29, original).
 *
 * One widget definition renders in every size, tint and host. That is the whole
 * universality mechanism: `view()` receives size/tint/host and re-lays itself out.
 *
 * Hard rule: `load()` is the ONLY data path. There is no default data, no fallback
 * array and no generated numbers. If `load()` rejects, the host renders ErrorState.
 * `scripts/check-no-mock.mjs` fails the production build if mock markers appear.
 */
import type { ReactNode } from "react";
import type { JaegerSource } from "../api/source";

/** Sizes a widget can occupy. Neutral names; no third-party API symbols. */
export type WidgetSize = "sm" | "md" | "lg" | "xl" | "inline" | "circle" | "rect";

/** How the surface treats the widget's colours. */
export type WidgetTint = "full" | "tinted" | "dimmed";

/** Where the widget is mounted. */
export type WidgetHost = "page" | "float" | "overlay" | "menubar";

/** One user-pickable parameter. Rendered by the gallery's configuration sheet. */
export type ConfigField =
  | { key: string; type: "text"; label: string; placeholder?: string; required?: boolean }
  | { key: string; type: "select"; label: string; options: { value: string; label: string }[] }
  | { key: string; type: "number"; label: string; min?: number; max?: number }
  | { key: string; type: "boolean"; label: string };

/** Layout entry persisted per host. `v` guards future shape changes. */
export interface GridItem {
  /** Widget kind. */
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
  /**
   * Per-instance parameters (e.g. an AI-generated spec). Optional; absent for
   * built-in widgets. Persisted with the layout so a generated widget survives
   * reload exactly as the model produced it — never re-fetched or re-invented.
   */
  params?: Record<string, unknown>;
}

/** Persisted dashboard document. `v` must be bumped and migrated, never silently changed. */
export interface DashboardDoc {
  v: 1;
  hosts: Record<WidgetHost, GridItem[]>;
}

export interface WidgetRenderArgs<P = unknown, D = unknown> {
  data: D;
  size: WidgetSize;
  tint: WidgetTint;
  host: WidgetHost;
  params: P;
  /** When the data was read (ms). Shown as "as of …" when the source is slow. */
  observedAt: number;
  /** Re-run `load()`. Hosts pass this to action buttons and links. */
  reload: () => void;
}

export interface WidgetDef<P = void, D = unknown> {
  /** Stable id. Never rename after ship — it is a persisted layout key. */
  kind: string;
  title: string;
  /** Action verb, sentence case. Shown in the gallery. */
  about: string;
  sizes: WidgetSize[];
  hosts: WidgetHost[];
  config?: ConfigField[];
  /** Shown while `load()` is in flight. Must not display data. */
  skeleton: ReactNode;
  /**
   * The only data path. Resolves with real data or rejects.
   * Never returns placeholder values.
   */
  load(source: JaegerSource, params: P): Promise<D>;
  /** One view for every size/tint/host. */
  view(args: WidgetRenderArgs<P, D>): ReactNode;
}

/** Narrow a definition without losing its parameter type at the call site. */
export type AnyWidgetDef = WidgetDef<unknown, unknown>;
