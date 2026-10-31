/** Shared size classes (RESPONSIVE-SYSTEM.md §1, 2026-10-31). Width of the measured container, never device/UA.
 * compact <600 · medium 600–839 · regular 840–1199 · expanded 1200–1599 · wide ≥1600; `short` = height <500. CSS mirrors these numbers. */
import { useEffect, useState, type RefObject } from "react";

export const BREAKPOINTS = { medium: 600, regular: 840, expanded: 1200, wide: 1600 } as const;
export type SizeClass = "compact" | "medium" | "regular" | "expanded" | "wide";
export function sizeClass(width: number): SizeClass {
  return width >= BREAKPOINTS.wide ? "wide" : width >= BREAKPOINTS.expanded ? "expanded" : width >= BREAKPOINTS.regular ? "regular" : width >= BREAKPOINTS.medium ? "medium" : "compact";
}
export const isShort = (height: number) => height < 500;

/** Size class of an element's inline size (ResizeObserver), plus the viewport `short` modifier. */
export function useSizeClass(ref: RefObject<HTMLElement | null>): { cls: SizeClass; short: boolean } {
  const read = () => ({ cls: sizeClass(ref.current?.clientWidth ?? (typeof window !== "undefined" ? window.innerWidth : 1440)), short: typeof window !== "undefined" && isShort(window.innerHeight) });
  const [v, setV] = useState(read);
  useEffect(() => {
    const el = ref.current; const upd = () => setV((o) => { const n = read(); return n.cls === o.cls && n.short === o.short ? o : n; });
    upd(); window.addEventListener("resize", upd);
    const ro = el && typeof ResizeObserver !== "undefined" ? new ResizeObserver(upd) : null; if (el) ro?.observe(el);
    return () => { window.removeEventListener("resize", upd); ro?.disconnect(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref]);
  return v;
}
