/* Modified from AetherStudio studio/src/main.tsx Studio() (Apache-2.0, ece0209):
 * the aside.studio-sidebar + div.studio-body > main.studio-content layout,
 * reduced to slots: top / primary / sections / footer, and the main content.
 * Web/dev renders it as a floating rounded window on a backdrop; the native
 * macOS host (html[data-jaeger-host="macos"]) fills its window edge to edge.
 * Jenkins Robotics 2026-10-17: resizable sidebar (sidebarSizing.ts) with an
 * 88px rail, auto-collapse on narrow windows and a remembered width. */
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { SIDEBAR, dragTo, keyAdjust, layout, parsePrefs, serializePrefs, toggle, type SidebarPrefs } from "./sidebarSizing";

import { currentTextSize, TEXT_SIZE_EVENT } from "../settings/textSize";

export interface SidebarControl { collapsed: boolean; toggle: () => void }

interface AppShellProps {
  /** Sidebar header: traffic-light band, sidebar toggle, search and + (window drag region). A function
   * gets the collapse state and the animated toggle (the header's sidebar button). */
  top: ReactNode | ((sidebar: SidebarControl) => ReactNode);
  /** Pinned supervisor + specialist list. */
  primary: ReactNode;
  /** Secondary entries (Tasks). */
  sections?: ReactNode;
  /** User avatar, Connect apps. */
  footer: ReactNode;
  children: ReactNode;
}

function loadPrefs(): SidebarPrefs {
  try { return parsePrefs(localStorage.getItem(SIDEBAR.storageKey)); } catch { return parsePrefs(null); }
}

export function AppShell({ top, primary, sections, footer, children }: AppShellProps) {
  const shellRef = useRef<HTMLDivElement>(null);
  const [prefs, setPrefs] = useState<SidebarPrefs>(loadPrefs);
  const [shellWidth, setShellWidth] = useState(0);
  const [resizing, setResizing] = useState(false);
  const [animating, setAnimating] = useState(false);
  const dragBase = useRef<SidebarPrefs | null>(null);

  // Width of the shell (the window in the macOS host); jsdom has no layout, so fall back to innerWidth.
  useLayoutEffect(() => {
    const el = shellRef.current;
    const measure = () => setShellWidth(el?.getBoundingClientRect().width || window.innerWidth);
    measure();
    window.addEventListener("resize", measure);
    const ro = typeof ResizeObserver === "function" && el ? new ResizeObserver(measure) : null;
    if (ro && el) ro.observe(el);
    return () => { window.removeEventListener("resize", measure); ro?.disconnect(); };
  }, []);

  useEffect(() => {
    try { localStorage.setItem(SIDEBAR.storageKey, serializePrefs(prefs)); } catch { /* storage unavailable */ }
  }, [prefs]);

  useEffect(() => {
    if (!animating) return;
    const t = window.setTimeout(() => setAnimating(false), SIDEBAR.toggleMs + 20);
    return () => window.clearTimeout(t);
  }, [animating]);

  const [textSize, setTextSize] = useState(currentTextSize);
  useEffect(() => { const sync = () => setTextSize(currentTextSize()); window.addEventListener(TEXT_SIZE_EVENT, sync); return () => window.removeEventListener(TEXT_SIZE_EVENT, sync); }, []);
  const lay = layout(prefs, shellWidth * Math.min(1, 14 / textSize));

  /** Only a toggle animates (never a drag or a window resize). */
  const apply = useCallback((next: SidebarPrefs, animate: boolean) => {
    setPrefs((cur) => {
      if (animate && next.isCollapsed !== cur.isCollapsed) setAnimating(true);
      return next;
    });
  }, []);

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    dragBase.current = prefs;
    setResizing(true);
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!dragBase.current || !shellRef.current) return;
    const raw = e.clientX - shellRef.current.getBoundingClientRect().left;
    apply(dragTo(dragBase.current, raw), false);
  };
  const endDrag = (e: PointerEvent<HTMLDivElement>) => {
    if (!dragBase.current) return;
    dragBase.current = null;
    setResizing(false);
    e.currentTarget.releasePointerCapture?.(e.pointerId);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const next = keyAdjust(prefs, e.key);
    if (!next) return;
    e.preventDefault();
    apply(next, e.key === "Enter" || e.key === " " || next.isCollapsed !== prefs.isCollapsed);
  };

  const className = [
    "jg-shell",
    lay.mode === "rail" ? "is-rail" : "",
    lay.auto ? "is-auto-rail" : "",
    animating ? "is-animating" : "",
    resizing ? "is-resizing" : "",
  ].filter(Boolean).join(" ");
  const style = { "--jg-sidebar-column": `${lay.width}px` } as CSSProperties;

  return (
    <div className="jg-desktop aether-home-theme">
      <div ref={shellRef} className={className} style={style} data-sidebar={lay.mode}>
        <aside className="jg-shell__sidebar" aria-label="Agents">
          <div className="jg-shell__top">{typeof top === "function" ? top({ collapsed: lay.mode === "rail", toggle: () => apply(toggle(prefs), true) }) : top}</div>
          <div className="jg-shell__primary">{primary}{sections}</div>
          <div className="jg-shell__footer">{footer}</div>
        </aside>
        <div
          className="jg-sidebar-handle"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize sidebar"
          aria-valuemin={SIDEBAR.railWidth}
          aria-valuemax={SIDEBAR.maxWidth}
          aria-valuenow={lay.width}
          tabIndex={0}
          title="Drag to resize · double-click to collapse"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onDoubleClick={() => apply(toggle(prefs), true)}
          onKeyDown={onKeyDown}
        />
        <div className="jg-shell__body">
          <main className="jg-shell__content">{children}</main>
        </div>
      </div>
    </div>
  );
}
