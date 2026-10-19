/* Sidebar sizing (Jenkins Robotics, 2026-10-17, original). Pure helpers: no DOM, no storage access.
 * Behaviour follows the measured Grok Bot desktop sidebar (Jaeger-Mac-App-Improvement-Guide.md):
 * 280 default, 240–400 while dragging, a drag below 210 collapses to an 88px rail, the sidebar
 * auto-collapses while the window is narrower than width + 424, arrow keys step by 8, and
 * {expandedWidth, isCollapsed} is what gets remembered. */

export const SIDEBAR = {
  defaultWidth: 280,
  minWidth: 240,
  maxWidth: 400,
  railWidth: 88,
  collapseBelow: 210,
  contentMin: 424,
  keyStep: 8,
  toggleMs: 200,
  storageKey: "jaeger.sidebar.v1",
} as const;

export interface SidebarPrefs {
  /** Width when expanded (kept while collapsed so expanding restores it). */
  expandedWidth: number;
  /** The user's own collapse choice (auto-collapse is not stored). */
  isCollapsed: boolean;
}

export interface SidebarLayout {
  mode: "expanded" | "rail";
  /** Column width in px. */
  width: number;
  /** True when the rail is only because the window is too narrow. */
  auto: boolean;
}

export const defaultPrefs: SidebarPrefs = { expandedWidth: SIDEBAR.defaultWidth, isCollapsed: false };

export function clampWidth(width: number): number {
  if (!Number.isFinite(width)) return SIDEBAR.defaultWidth;
  return Math.min(SIDEBAR.maxWidth, Math.max(SIDEBAR.minWidth, Math.round(width)));
}

/** Stored JSON → prefs; anything malformed falls back to the defaults. */
export function parsePrefs(raw: string | null | undefined): SidebarPrefs {
  if (!raw) return { ...defaultPrefs };
  try {
    const v = JSON.parse(raw) as Partial<SidebarPrefs> | null;
    if (!v || typeof v !== "object") return { ...defaultPrefs };
    return {
      expandedWidth: typeof v.expandedWidth === "number" ? clampWidth(v.expandedWidth) : SIDEBAR.defaultWidth,
      isCollapsed: v.isCollapsed === true,
    };
  } catch {
    return { ...defaultPrefs };
  }
}

export function serializePrefs(prefs: SidebarPrefs): string {
  return JSON.stringify({ expandedWidth: clampWidth(prefs.expandedWidth), isCollapsed: prefs.isCollapsed });
}

/** Dragging the edge to a raw width (pointer x relative to the shell's left edge). */
export function dragTo(prefs: SidebarPrefs, rawWidth: number): SidebarPrefs {
  if (rawWidth < SIDEBAR.collapseBelow) return { ...prefs, isCollapsed: true };
  return { expandedWidth: clampWidth(rawWidth), isCollapsed: false };
}

export function toggle(prefs: SidebarPrefs): SidebarPrefs {
  return { ...prefs, isCollapsed: !prefs.isCollapsed };
}

/** Keyboard on the separator; null when the key is not ours. */
export function keyAdjust(prefs: SidebarPrefs, key: string): SidebarPrefs | null {
  switch (key) {
    case "ArrowLeft":
      if (prefs.isCollapsed) return prefs;
      if (prefs.expandedWidth <= SIDEBAR.minWidth) return { ...prefs, isCollapsed: true };
      return { ...prefs, expandedWidth: clampWidth(prefs.expandedWidth - SIDEBAR.keyStep) };
    case "ArrowRight":
      if (prefs.isCollapsed) return { ...prefs, isCollapsed: false };
      return { ...prefs, expandedWidth: clampWidth(prefs.expandedWidth + SIDEBAR.keyStep) };
    case "Home":
      return { expandedWidth: SIDEBAR.minWidth, isCollapsed: false };
    case "End":
      return { expandedWidth: SIDEBAR.maxWidth, isCollapsed: false };
    case "Enter":
    case " ":
      return toggle(prefs);
    default:
      return null;
  }
}

/** The window (shell) is too narrow for this sidebar plus the minimum content column. */
export function autoCollapses(shellWidth: number, expandedWidth: number): boolean {
  return shellWidth > 0 && shellWidth < clampWidth(expandedWidth) + SIDEBAR.contentMin;
}

export function layout(prefs: SidebarPrefs, shellWidth: number): SidebarLayout {
  if (prefs.isCollapsed) return { mode: "rail", width: SIDEBAR.railWidth, auto: false };
  if (autoCollapses(shellWidth, prefs.expandedWidth)) return { mode: "rail", width: SIDEBAR.railWidth, auto: true };
  return { mode: "expanded", width: clampWidth(prefs.expandedWidth), auto: false };
}
