/**
 * Layout presets (Jenkins Robotics, 2026-10-31, original). One choice restyles the whole app:
 * chrome (nav position, command bar), page grid and spacing, stat typography, charts and controls.
 * Each preset is a layout config (read by AppChrome) plus a token set in presets.css keyed on
 * <html data-layout>. The choice lives in the Gateway (/v1/ui/layout) so the Mac app, browser and
 * iPhone share it; localStorage is the offline fallback and first-paint value.
 */
import { useEffect, useState } from "react";
import { getJson, sendJson } from "../unified/webui";

export type PresetId = "glass" | "arc" | "linear" | "dia";
export interface LayoutConfig {
  /** Where navigation lives on Mac/tablet widths. "sidebar" = no top bar (Arc). */
  nav: "topbar+sidebar" | "sidebar";
  /** ⌘K entry: a big floating field, a field inside the sidebar, or a merged search+ask field. */
  command: "floating" | "sidebar" | "field" | "ask";
  /** Translucent materials (backdrop blur) on cards and sidebar. */
  glass: boolean;
}
export interface Preset { id: PresetId; label: string; note: string; layout: LayoutConfig }

export const PRESETS: readonly Preset[] = [
  { id: "glass", label: "Glass", note: "Liquid Glass toolbar capsules and a big ⌘K bar",
    layout: { nav: "topbar+sidebar", command: "floating", glass: true } },
  { id: "arc", label: "Arc", note: "No top bar; everything in a translucent sidebar",
    layout: { nav: "sidebar", command: "sidebar", glass: true } },
  { id: "linear", label: "Linear", note: "Dark, dense sidebar; ⌘K first",
    layout: { nav: "topbar+sidebar", command: "field", glass: false } },
  { id: "dia", label: "Dia", note: "Warm minimal bar; search and ask in one field",
    layout: { nav: "topbar+sidebar", command: "ask", glass: false } },
] as const;

export const DEFAULT_PRESET: PresetId = "glass";
export const PRESET_KEY = "appearance.layout";
export const LAYOUT_ENDPOINT = "/v1/ui/layout";

export const isPreset = (v: unknown): v is PresetId => PRESETS.some((p) => p.id === v);
export const presetOf = (id: PresetId): Preset => PRESETS.find((p) => p.id === id) ?? PRESETS[0];

export function storedPreset(): PresetId {
  try { const v = localStorage.getItem(PRESET_KEY); return isPreset(v) ? v : DEFAULT_PRESET; } catch { return DEFAULT_PRESET; }
}

const listeners = new Set<(p: PresetId) => void>();
let current: PresetId | null = null;

/** Sets data-layout / data-nav / data-command on <html> and remembers it locally. */
export function applyPreset(id: PresetId) {
  const p = presetOf(id);
  current = p.id;
  try { localStorage.setItem(PRESET_KEY, p.id); } catch { /* storage unavailable */ }
  const d = document.documentElement.dataset;
  d.layout = p.id; d.nav = p.layout.nav; d.command = p.layout.command; d.glass = String(p.layout.glass);
  listeners.forEach((l) => l(p.id));
}

/** Pulls the shared choice from the Gateway; keeps the local one when offline. */
export async function syncPresetFromGateway(): Promise<PresetId> {
  try {
    const r = await getJson<{ preset?: string }>(LAYOUT_ENDPOINT);
    if (isPreset(r.preset) && r.preset !== current) applyPreset(r.preset);
  } catch { /* gateway unreachable: local fallback stays */ }
  return current ?? storedPreset();
}

/** Applies now, then saves to the Gateway so every device follows. Returns false if only saved locally. */
export async function choosePreset(id: PresetId): Promise<boolean> {
  applyPreset(id);
  try { await sendJson("POST", LAYOUT_ENDPOINT, { preset: id }); return true; } catch { return false; }
}

export function usePreset(): Preset {
  const [id, setId] = useState<PresetId>(() => current ?? storedPreset());
  useEffect(() => { listeners.add(setId); return () => { listeners.delete(setId); }; }, []);
  return presetOf(id);
}
