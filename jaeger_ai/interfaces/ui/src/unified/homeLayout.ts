/** Home panel order (rearrangeable, persisted per device). */
export const HOME_PANELS = ["gateway", "cpu", "mem", "gpu", "disk", "agents", "tasks", "approvals", "recent"] as const;
export type HomePanel = typeof HOME_PANELS[number];
export const HOME_LAYOUT_KEY = "jaeger.home.panels.v1";

export function loadPanels(storage: Pick<Storage, "getItem"> | undefined = globalThis.localStorage): HomePanel[] {
  try {
    const saved = JSON.parse(storage?.getItem(HOME_LAYOUT_KEY) ?? "[]") as unknown[];
    const known = saved.filter((p): p is HomePanel => (HOME_PANELS as readonly unknown[]).includes(p));
    return [...new Set([...known, ...HOME_PANELS])];
  } catch { return [...HOME_PANELS]; }
}
export function savePanels(order: HomePanel[], storage: Pick<Storage, "setItem"> | undefined = globalThis.localStorage) {
  try { storage?.setItem(HOME_LAYOUT_KEY, JSON.stringify(order)); } catch { /* unavailable */ }
}
export function movePanel(order: HomePanel[], id: HomePanel, to: number): HomePanel[] {
  const next = order.filter((p) => p !== id);
  next.splice(Math.max(0, Math.min(to, next.length)), 0, id);
  return next;
}
