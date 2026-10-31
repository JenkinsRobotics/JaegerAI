/**
 * Unified UI primitives (2026-10-30): Segmented, Skeleton, Empty, Toasts, Sheet, Sparkline, Badge.
 * Styling in design.css; see DESIGN.md.
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const idx = options.findIndex((o) => o.value === value);
  const move = (d: number) => { const n = (idx + d + options.length) % options.length; onChange(options[n].value); refs.current[n]?.focus(); };
  return (
    <div className="jg-ui-seg" role="radiogroup" aria-label={label}
      onKeyDown={(e) => { if (e.key === "ArrowRight") { e.preventDefault(); move(1); } else if (e.key === "ArrowLeft") { e.preventDefault(); move(-1); } }}>
      {options.map((o, i) => (
        <button key={o.value} ref={(el) => { refs.current[i] = el; }} type="button" role="radio" aria-checked={o.value === value} tabIndex={o.value === value ? 0 : -1} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}

export const Skeleton = ({ w = "100%", h = 12 }: { w?: number | string; h?: number }) => <span className="jg-ui-skel" style={{ width: w, height: h }} aria-hidden="true" />;
export const SkeletonRows = ({ n = 3 }: { n?: number }) => (
  <div role="status" aria-label="Loading" style={{ display: "grid", gap: 10 }}>{Array.from({ length: n }, (_, i) => <Skeleton key={i} w={`${90 - i * 12}%`} h={14} />)}</div>
);

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return <div className="jg-ui-empty"><strong>{title}</strong>{children && <span>{children}</span>}{action}</div>;
}

export type Tone = "ok" | "warn" | "bad" | undefined;
export const Badge = ({ tone, children }: { tone?: Tone; children: ReactNode }) => <span className="jg-ui-badge" data-tone={tone}>{children}</span>;

interface Toast { id: number; text: string; tone?: "error" }
const ToastCtx = createContext<(text: string, tone?: "error") => void>(() => {});
export const useToast = () => useContext(ToastCtx);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone?: "error") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, text, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === "error" ? 7000 : 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="jg-ui-toasts" role="status" aria-live="polite">
        {toasts.map((t) => <div key={t.id} className="jg-ui-toast" data-tone={t.tone}>{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}

export function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    panel.current?.querySelector<HTMLElement>("input, textarea, select, button")?.focus();
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    addEventListener("keydown", key);
    return () => { removeEventListener("keydown", key); prev?.focus?.(); };
  }, [onClose]);
  return (
    <div className="jg-ui-sheet" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={panel} className="jg-ui-sheet__panel" role="dialog" aria-modal="true" aria-label={title}><h2>{title}</h2>{children}</div>
    </div>
  );
}

/** Minimal time-series line (SVG). `values` may contain nulls (gaps). */
export function Sparkline({ values, max, height = 56, label, color = "var(--jg-color-accent)" }: { values: (number | null)[]; max?: number; height?: number; label: string; color?: string }) {
  const w = 240;
  const nums = values.filter((v): v is number => v != null);
  if (nums.length < 2) return <div className="jg-ui-spark jg-ui-spark--empty" style={{ height }} role="img" aria-label={`${label}: collecting data`}><Skeleton h={height - 16} /></div>;
  const top = max ?? Math.max(1, ...nums) * 1.15;
  const step = w / Math.max(1, values.length - 1);
  let d = "", pen = false;
  values.forEach((v, i) => {
    if (v == null) { pen = false; return; }
    const y = height - 4 - (Math.min(v, top) / top) * (height - 8);
    d += `${pen ? "L" : "M"}${(i * step).toFixed(1)},${y.toFixed(1)}`; pen = true;
  });
  const last = nums[nums.length - 1];
  return (
    <svg className="jg-ui-spark" viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" width="100%" height={height} role="img" aria-label={`${label}: latest ${Math.round(last * 10) / 10}`}>
      {nums.length === values.length && <path d={`${d}L${w},${height}L0,${height}Z`} fill={color} opacity=".10" />}
      <path d={d} fill="none" stroke={color} strokeWidth="1.75" vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

// ── Page shell (one per page): title, subtitle, actions; merged tabs add sub-tabs above ──

/** The one page header: h1 title, optional subtitle, actions on the right (wraps on phone). */
export function PageHead({ title, subtitle, actions, children }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children?: ReactNode }) {
  return (
    <header className="jg-u-page__head">
      <div className="jg-u-page__title"><h1>{title}</h1>{subtitle != null && subtitle !== false && <p>{subtitle}</p>}</div>
      {actions && <div className="jg-ui-toolbar">{actions}</div>}
      {children}
    </header>
  );
}

/** Sub-tabs of a merged page: a segmented tab strip; each tab is a real route. */
export function SubTabs({ label, tabs, active, onPick }: { label: string; tabs: readonly { id: string; title: string }[]; active: string; onPick: (id: string) => void }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const idx = Math.max(0, tabs.findIndex((t) => t.id === active));
  const move = (d: number) => { const n = (idx + d + tabs.length) % tabs.length; onPick(tabs[n].id); refs.current[n]?.focus(); };
  return (
    <nav className="jg-subtabs" aria-label={label}>
      <div className="jg-ui-seg" role="tablist" aria-label={label}
        onKeyDown={(e) => { if (e.key === "ArrowRight") { e.preventDefault(); move(1); } else if (e.key === "ArrowLeft") { e.preventDefault(); move(-1); } }}>
        {tabs.map((t, i) => (
          <button key={t.id} ref={(el) => { refs.current[i] = el; }} type="button" role="tab" aria-selected={t.id === active} aria-checked={t.id === active}
            tabIndex={t.id === active ? 0 : -1} onClick={() => onPick(t.id)}>{t.title}</button>
        ))}
      </div>
    </nav>
  );
}

/** A merged page: sub-tab strip + the active sub-page. Visited sub-pages stay mounted so streams and drafts survive. */
export function TabbedPage({ label, tabs, active, onPick, render, banner }: { label: string; tabs: readonly { id: string; title: string }[]; active: string; onPick: (id: string) => void; render: (id: string) => ReactNode; banner?: ReactNode }) {
  const [seen, setSeen] = useState<string[]>([active]);
  useEffect(() => { setSeen((s) => (s.includes(active) ? s : [...s, active])); }, [active]);
  return (
    <div className="jg-tabbed">
      <SubTabs label={label} tabs={tabs} active={active} onPick={onPick} />
      {banner}
      <div className="jg-tabbed__body">
        {tabs.filter((t) => seen.includes(t.id) || t.id === active).map((t) => (
          <div key={t.id} className="jg-tabbed__pane" role="tabpanel" aria-label={t.title} hidden={t.id !== active}>{render(t.id)}</div>
        ))}
      </div>
    </div>
  );
}
