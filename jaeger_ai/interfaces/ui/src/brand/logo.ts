/**
 * Jaeger logo marks (J-085). Crisp inline vectors in currentColor / --jg-color-accent so every layout
 * preset (Glass, Arc, Linear, Dia), feel and light/dark theme restyles them. The choice is shared
 * through the Gateway (/v1/ui/logo, ~/.jaeger/ui/logo.json) with localStorage as first-paint and
 * offline fallback, the same way the layout preset is. A custom SVG/PNG is sanitized by the Gateway.
 */
import { useEffect, useState } from "react";
import { getJson, sendJson } from "../unified/webui";

/** The original traced Jenkins Robotics shield J (Design-Specs/assets/shield-mark.svg), kept as an option. */
export const SHIELD_J_PATH = "M583.0,630.9C682.8,558.3 765.3,498.3 766.2,497.6C767.8,496.4 762.5,479.4 697.8,280.2L627.7,64.0L401.0,64.0L174.3,64.0L104.2,280.2C39.7,479.0 34.2,496.4 35.8,497.6C36.7,498.3 119.2,558.3 219.0,630.9C318.8,703.5 400.7,763.0 401.0,763.0C401.3,763.0 483.2,703.5 583.0,630.9ZM387.4,690.6C326.8,671.0 153.3,546.3 107.0,489.1C95.7,475.2 94.6,472.6 94.2,458.5C93.0,420.8 116.2,328.6 150.8,233.5C173.6,170.8 198.4,121.3 211.8,111.5C230.5,98.0 300.5,90.0 400.9,90.0C498.5,90.0 568.7,97.7 589.1,110.5C611.8,124.9 660.2,243.4 690.8,359.5C702.9,405.2 708.4,437.7 707.8,458.5C707.4,472.6 706.3,475.2 695.0,489.1C653.8,540.1 506.1,649.3 432.5,683.3C410.4,693.5 401.0,695.0 387.4,690.6ZM421.0,641.4C427.9,639.4 439.8,633.0 447.0,627.5C452.9,622.9 503.6,576.9 505.8,574.2C506.7,573.0 507.0,533.7 507.0,385.9L507.0,199.1L483.0,170.8C457.0,140.2 455.2,138.6 447.1,139.4C442.5,139.8 438.8,142.0 435.7,146.3C433.8,148.8 433.7,151.5 432.9,219.2C431.5,340.9 430.0,492.8 430.0,514.4L430.0,535.1L424.6,540.5C420.6,544.5 418.0,546.2 414.0,547.4C402.7,550.8 396.0,549.1 387.2,540.7C376.8,530.6 353.5,505.1 347.0,496.5C330.9,475.2 329.3,461.9 338.9,428.6C346.8,401.1 350.4,380.7 348.6,373.6C347.6,369.7 344.5,367.0 341.0,367.0C334.0,367.0 325.0,374.0 299.6,398.9C273.0,425.2 264.3,436.6 258.5,452.8C254.7,463.6 253.7,471.0 254.3,483.3C254.8,494.5 257.5,504.9 262.7,516.7C264.6,521.1 346.2,614.4 355.2,622.5C365.4,631.7 380.5,639.6 393.4,642.6C400.7,644.2 413.1,643.7 421.0,641.4ZM393.4,633.6C390.6,632.9 384.9,630.7 380.9,628.8C365.0,621.1 362.4,618.6 315.7,565.6C271.3,515.3 269.9,513.5 266.3,501.7C264.3,494.9 265.3,494.8 268.0,501.5C269.9,506.1 276.9,514.3 312.1,552.7C336.5,579.4 356.8,600.7 360.7,603.8C368.7,610.0 383.1,617.4 391.5,619.5C404.1,622.7 417.5,620.9 430.4,614.4C440.2,609.4 445.5,605.2 472.7,581.3C486.0,569.6 497.1,560.0 497.4,560.0C497.7,560.0 498.0,562.2 498.0,564.9L498.0,569.9L471.9,593.7C457.5,606.8 443.0,619.5 439.6,622.0C423.8,633.5 408.6,637.3 393.4,633.6Z";
export const SHIELD_J_VIEWBOX = "30 58 742 712";

export const LOGOS = [
  { id: "shield-j", label: "Shield J", note: "Brand mark, redrawn" },
  { id: "shield-j-original", label: "Original", note: "Traced brand mark" },
  { id: "shield-j-tile", label: "Shield J Tile", note: "Accent tile" },
  { id: "shield", label: "Shield", note: "Outline only" },
  { id: "j", label: "J Monogram", note: "Minimal" },
  { id: "wordmark", label: "Wordmark", note: "Shield + JAEGER" },
  { id: "classic", label: "Classic", note: "Red app icon" },
] as const;
export type BuiltinLogo = (typeof LOGOS)[number]["id"];
export type LogoId = BuiltinLogo | "custom";
export interface LogoState { id: LogoId; custom?: string }

export const LOGO_KEY = "appearance.logo";
export const LOGO_CUSTOM_KEY = "appearance.logo.custom";
export const LOGO_ENDPOINT = "/v1/ui/logo";
export const DEFAULT_LOGO: BuiltinLogo = "shield-j";
const isBuiltin = (v: unknown): v is BuiltinLogo => LOGOS.some((l) => l.id === v);

const get = (k: string) => { try { return localStorage.getItem(k); } catch { return null; } };
const set = (k: string, v: string | null) => { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch { /* storage unavailable */ } };

export function storedLogo(): LogoState {
  const id = get(LOGO_KEY); const custom = get(LOGO_CUSTOM_KEY) ?? undefined;
  if (id === "custom" && custom?.startsWith("data:image/")) return { id: "custom", custom };
  return { id: isBuiltin(id) ? id : DEFAULT_LOGO, custom };
}

let current: LogoState | undefined;
const listeners = new Set<(s: LogoState) => void>();
export function applyLogo(s: LogoState) {
  current = s;
  set(LOGO_KEY, s.id); if (s.custom) set(LOGO_CUSTOM_KEY, s.custom);
  listeners.forEach((l) => l(s));
}

export async function syncLogoFromGateway(): Promise<LogoState> {
  try {
    const r = await getJson<{ logo?: string; custom?: { data_url?: string } }>(LOGO_ENDPOINT);
    if (r.logo === "custom" && r.custom?.data_url?.startsWith("data:image/")) applyLogo({ id: "custom", custom: r.custom.data_url });
    else if (isBuiltin(r.logo)) applyLogo({ ...(current ?? storedLogo()), id: r.logo });
  } catch { /* gateway unreachable: local choice stays */ }
  return current ?? storedLogo();
}

/** Applies now, then shares it. Returns false when only saved on this device. */
export async function chooseLogo(id: LogoId): Promise<boolean> {
  const prev = current ?? storedLogo();
  if (id === "custom" && !prev.custom) return false;
  applyLogo({ ...prev, id });
  const m = id === "custom" ? /^data:([^;]+);base64,(.*)$/.exec(prev.custom ?? "") : null;
  const body = m ? { logo: "custom", custom: { mime: m[1], data_base64: m[2] } } : { logo: id };
  try { await sendJson("POST", LOGO_ENDPOINT, body); return true; } catch { return false; }
}

const MIME = /^image\/(svg\+xml|png|webp|jpeg)$/;
/** Sends a custom SVG/PNG/WebP/JPEG to the Gateway, which sanitizes and stores it; uses its cleaned copy. */
export async function uploadCustomLogo(f: File): Promise<void> {
  if (!MIME.test(f.type)) throw new Error("Use an SVG, PNG, WebP or JPEG file");
  if (f.size > 200_000) throw new Error("The logo file must be under 200 KB");
  const buf = new Uint8Array(await f.arrayBuffer());
  let bin = ""; for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  const r = await sendJson<{ custom?: { data_url?: string } }>("POST", LOGO_ENDPOINT, { logo: "custom", custom: { mime: f.type, data_base64: btoa(bin) } });
  if (!r.custom?.data_url) throw new Error("The Gateway did not return the cleaned logo");
  applyLogo({ id: "custom", custom: r.custom.data_url });
}

export function useLogo(): LogoState {
  const [s, setS] = useState<LogoState>(() => current ?? storedLogo());
  useEffect(() => { listeners.add(setS); return () => { listeners.delete(setS); }; }, []);
  return s;
}
