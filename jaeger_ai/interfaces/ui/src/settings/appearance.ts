/** Appearance keys shared with the Mac app / IDE (SPEC-01/02): appearance.feel | appearance.icon | appearance.density. */
export const FEELS = [
  { id: "jaeger", label: "Jaeger", note: "House default, Jaeger Blue" },
  { id: "shield-mono", label: "Shield Mono", note: "High contrast" },
  { id: "ares-bronze", label: "ARES Bronze", note: "Bronze accent" },
  { id: "mission-control", label: "Mission Control", note: "Ops console" },
  { id: "aurora", label: "Aurora", note: "Cool gradient" },
  { id: "vscode", label: "VS Code", note: "IDE look" },
  { id: "grok", label: "Grok", note: "Monochrome" },
] as const;
export type Feel = (typeof FEELS)[number]["id"];
export const FEEL_KEY = "appearance.feel";
export const ICON_KEY = "appearance.icon";
export const DENSITY_KEY = "appearance.density";

const get = (k: string) => { try { return localStorage.getItem(k); } catch { return null; } };
const set = (k: string, v: string | null) => { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch { /* storage unavailable */ } };

export function storedFeel(): Feel { const v = get(FEEL_KEY); return (FEELS.some((f) => f.id === v) ? v : "jaeger") as Feel; }
/** Sets data-feel on <html> (generated feels.css restyles in the same frame) and the PWA theme-color. */
export function applyFeel(feel: Feel) {
  set(FEEL_KEY, feel);
  document.documentElement.dataset.feel = feel;
  syncThemeColor();
}
export function syncThemeColor() {
  const bg = getComputedStyle(document.documentElement).getPropertyValue("--jg-color-chrome").trim() || getComputedStyle(document.body).backgroundColor;
  let m = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (!m) { m = document.createElement("meta"); m.name = "theme-color"; document.head.append(m); }
  if (bg) m.content = bg;
}

export const BUILTIN_ICONS = [
  { id: "shield-blue", label: "Shield J Blue", src: "/icons/shield-blue-512.png", touch: "/icons/shield-blue-180.png" },
  { id: "shield-dark", label: "Shield J Dark", src: "/icons/shield-dark-512.png" },
  { id: "shield-light", label: "Shield J Light", src: "/icons/shield-light-512.png" },
  { id: "classic", label: "Classic J", src: "/jaeger-icon-512.png", touch: "/jaeger-icon-180.png" },
] as const;
export interface IconChoice { id: string; label: string; src: string; touch?: string; custom?: boolean }
export const CUSTOM_ICONS_KEY = "appearance.icons.custom";
export function customIcons(): IconChoice[] { try { return JSON.parse(get(CUSTOM_ICONS_KEY) ?? "[]"); } catch { return []; } }
export function saveCustomIcons(list: IconChoice[]) { set(CUSTOM_ICONS_KEY, JSON.stringify(list)); }
export function storedIcon(): string { return get(ICON_KEY) ?? "shield-blue"; }
/** Updates favicon + apple-touch-icon now (the Home Screen icon only changes after re-adding the PWA). */
export function applyIcon(id: string) {
  const all: IconChoice[] = [...BUILTIN_ICONS, ...customIcons()];
  const c = all.find((x) => x.id === id) ?? BUILTIN_ICONS[0];
  set(ICON_KEY, c.id);
  const link = (rel: string) => { let l = document.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`); if (!l) { l = document.createElement("link"); l.rel = rel; document.head.append(l); } return l; };
  const icon = link("icon"); icon.href = c.src; icon.type = c.src.endsWith(".svg") ? "image/svg+xml" : "image/png";
  link("apple-touch-icon").href = c.touch ?? c.src;
}

export type Density = "comfortable" | "compact";
export function storedDensity(): Density { return get(DENSITY_KEY) === "compact" ? "compact" : "comfortable"; }
export function applyDensity(d: Density) { set(DENSITY_KEY, d); document.documentElement.dataset.density = d; }

/** Checks a custom icon file: PNG/WebP/JPEG, square, ≥512 px. Returns a reason or null. */
export function iconProblem(w: number, h: number, type: string): string | null {
  if (!/^image\/(png|webp|jpeg)$/.test(type)) return "Use a PNG, WebP or JPEG image (ICNS: export a 1024 px PNG first)";
  if (w !== h) return `The icon must be square (this one is ${w}×${h})`;
  if (w < 512) return `The icon must be at least 512×512 (this one is ${w}×${h})`;
  return null;
}
