/** Settings › Appearance (TAB-01 §3): layout preset, theme, feel, app icon (+ custom upload), text size, density. Tokens only. */
import { useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { applyDensity, applyFeel, applyIcon, BUILTIN_ICONS, customIcons, FEELS, iconProblem, saveCustomIcons, storedDensity, storedFeel, storedIcon, type Density, type Feel, type IconChoice } from "./appearance";
import { choosePreset, PRESETS, usePreset } from "../shell/layoutPresets";
import { applyTextSize, currentTextSize } from "./textSize";
import type { Appearance } from "./SettingsDialog";
import { avatarApi } from "../avatar/avatarModel";
import { LogoArt } from "../brand/JaegerMark";
import { chooseLogo, LOGOS, uploadCustomLogo, useLogo } from "../brand/logo";

/** Radiogroup with arrow-key roving selection. */
function RadioGrid<T extends string>({ label, value, items, onPick, className, render }: { label: string; value: T; items: readonly { id: T; label: string }[]; onPick: (v: T) => void; className: string; render: (i: { id: T; label: string }, on: boolean) => ReactNode }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: KeyboardEvent, i: number) => {
    const d = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!d) return; e.preventDefault();
    const n = (i + d + items.length) % items.length; onPick(items[n].id); refs.current[n]?.focus();
  };
  return (
    <div role="radiogroup" aria-label={label} className={className}>
      {items.map((it, i) => { const on = it.id === value; return (
        <button key={it.id} ref={(el) => { refs.current[i] = el; }} type="button" role="radio" aria-checked={on} tabIndex={on ? 0 : -1} className="jg-set-tile" data-on={on || undefined}
          onClick={() => onPick(it.id)} onKeyDown={(e) => onKey(e, i)}>{render(it, on)}</button>); })}
    </div>
  );
}

export function AppearancePanel({ appearance, onAppearance, Row, Section }: { appearance: Appearance; onAppearance: (a: Appearance) => void; Row: (p: { label: string; hint?: string; anchor?: string; children?: ReactNode }) => ReactNode; Section: (p: { title: string; anchor?: string; children: ReactNode }) => ReactNode }) {
  const preset = usePreset();
  const [layoutMsg, setLayoutMsg] = useState<string>();
  const [feel, setFeel] = useState<Feel>(storedFeel);
  const [icon, setIcon] = useState(storedIcon);
  const [customs, setCustoms] = useState<IconChoice[]>(customIcons);
  const [density, setDensity] = useState<Density>(storedDensity);
  const [textSize, setTextSize] = useState(currentTextSize);
  const logo = useLogo();
  const [logoMsg, setLogoMsg] = useState<{ tone: "ok" | "bad"; text: string }>();
  const logoItems = [...LOGOS, ...(logo.custom ? [{ id: "custom" as const, label: "Custom", note: "Your upload" }] : [])];
  const [iconMsg, setIconMsg] = useState<{ tone: "ok" | "bad"; text: string }>();
  const icons: IconChoice[] = [...BUILTIN_ICONS, ...customs];
  const upload = async (f: File) => {
    setIconMsg({ tone: "ok", text: "Checking…" });
    try {
      const url = URL.createObjectURL(f);
      const img = await new Promise<HTMLImageElement>((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error("That file isn't a readable image")); i.src = url; });
      URL.revokeObjectURL(url);
      const bad = iconProblem(img.naturalWidth, img.naturalHeight, f.type);
      if (bad) { setIconMsg({ tone: "bad", text: bad }); return; }
      const a = await avatarApi.upload(f.name, f); // stored on this Mac by SHA-256 (~/.jaeger/avatars/assets)
      const c: IconChoice = { id: `custom-${a.sha256.slice(0, 12)}`, label: f.name.replace(/\.[^.]+$/, "").slice(0, 24) || "Custom", src: `/v1/assets/${a.sha256}/file`, custom: true };
      const next = [...customs.filter((x) => x.id !== c.id), c]; saveCustomIcons(next); setCustoms(next);
      applyIcon(c.id); setIcon(c.id); setIconMsg({ tone: "ok", text: `${c.label} applied` });
    } catch (e) { setIconMsg({ tone: "bad", text: (e as Error).message }); }
  };
  const remove = (id: string) => { const next = customs.filter((x) => x.id !== id); saveCustomIcons(next); setCustoms(next); if (icon === id) { applyIcon("shield-blue"); setIcon("shield-blue"); } };
  return <>
    <Section title="Layout" anchor="layout">
      <RadioGrid label="Layout" className="jg-set-feels jg-set-layouts" value={preset.id} items={PRESETS}
        onPick={(id) => { void choosePreset(id).then((shared) => setLayoutMsg(shared ? "Saved for every device" : "Saved on this device only (Gateway unreachable)")); }}
        render={(i, on) => <><span className="jg-set-layout__preview" data-layout-preview={i.id} aria-hidden="true"><i /><i /></span><span>{i.label}</span><small className="jg-sheet__hint">{(i as (typeof PRESETS)[number]).note}</small>{on && <span className="jg-set-check" aria-hidden="true">✓</span>}</>} />
      {layoutMsg && <p className="jg-sheet__hint" role="status">{layoutMsg}</p>}
    </Section>
    <Section title="Theme" anchor="theme">
      <Row label="Theme" anchor="theme">
        <RadioGrid label="Theme" className="jg-set-seg" value={appearance} onPick={onAppearance}
          items={[{ id: "light", label: "Light" }, { id: "dark", label: "Dark" }, { id: "system", label: "System" }] as const} render={(i) => i.label} />
      </Row>
    </Section>
    <Section title="Feel" anchor="feel">
      <RadioGrid label="Feel" className="jg-set-feels" value={feel} items={FEELS} onPick={(f) => { setFeel(f); applyFeel(f); }}
        render={(i, on) => <><span className="jg-set-feel__swatch" data-feel-preview={i.id} aria-hidden="true"><i /><i /><i /></span><span>{i.label}</span>{on && <span className="jg-set-check" aria-hidden="true">✓</span>}</>} />
    </Section>
    <Section title="Logo" anchor="logo">
      <RadioGrid label="Logo" className="jg-set-icons jg-set-logos" value={logo.id} items={logoItems}
        onPick={(id) => { void chooseLogo(id).then((shared) => setLogoMsg({ tone: "ok", text: shared ? "Saved for every device" : "Saved on this device only (Gateway unreachable)" })); }}
        render={(i, on) => <><span className="jg-set-logo__preview" aria-hidden="true"><LogoArt id={i.id} custom={logo.custom} /></span><span>{i.label}</span>{on && <span className="jg-set-check" aria-hidden="true">✓</span>}</>} />
      <div className="jg-set-icons__actions">
        <label className="jg-u-btn">Upload logo…<input type="file" hidden accept="image/svg+xml,image/png,image/webp,image/jpeg" onChange={(e) => { const f = e.target.files?.[0]; if (f) { setLogoMsg({ tone: "ok", text: "Checking…" }); void uploadCustomLogo(f).then(() => setLogoMsg({ tone: "ok", text: "Custom logo applied on every device" }), (err: Error) => setLogoMsg({ tone: "bad", text: err.message })); } e.target.value = ""; }} /></label>
      </div>
      {logoMsg && <p className={logoMsg.tone === "bad" ? "jg-u-error" : "jg-sheet__hint"} role="status">{logoMsg.text}</p>}
      <p className="jg-sheet__hint">The mark on the Chat screen and in the top bar. Built-in marks follow your layout, feel and theme colors. Uploads: SVG, PNG, WebP or JPEG under 200 KB; SVGs are cleaned of scripts and links.</p>
    </Section>
    <Section title="App icon" anchor="icon">
      <RadioGrid label="App icon" className="jg-set-icons" value={icon} items={icons} onPick={(id) => { setIcon(id); applyIcon(id); }}
        render={(i) => <><img src={(i as IconChoice).src} alt="" width={48} height={48} /><span>{i.label}</span></>} />
      <div className="jg-set-icons__actions">
        <label className="jg-u-btn">Add custom…<input type="file" hidden accept="image/png,image/webp,image/jpeg" onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = ""; }} /></label>
        {customs.map((c) => <button key={c.id} type="button" className="jg-u-btn" onClick={() => remove(c.id)}>Remove {c.label}</button>)}
      </div>
      {iconMsg && <p className={iconMsg.tone === "bad" ? "jg-u-error" : "jg-sheet__hint"} role="status">{iconMsg.text}</p>}
      <p className="jg-sheet__hint">Updates this tab's icon now. On iPhone/iPad, re-add Jaeger to the Home Screen to change its Home Screen icon. The macOS menu bar always uses the template shield.</p>
    </Section>
    <Section title="Text" anchor="text-size">
      <Row label="Text size" hint="Saved on this device; chat, composer and sidebar text." anchor="text-size">
        <select className="jg-sheet__select" aria-label="Text size" value={textSize} onChange={(e) => setTextSize(applyTextSize(Number(e.target.value)))}>
          {Array.from({ length: 11 }, (_, i) => i + 12).map((size) => <option key={size} value={size}>{size}px{size === 14 ? " (Default)" : ""}</option>)}
        </select>
      </Row>
      <Row label="Density" hint="Compact trims 4px from rows (mouse/trackpad only)." anchor="density">
        <RadioGrid label="Density" className="jg-set-seg" value={density} onPick={(d) => { setDensity(d); applyDensity(d); }}
          items={[{ id: "comfortable", label: "Comfortable" }, { id: "compact", label: "Compact" }] as const} render={(i) => i.label} />
      </Row>
    </Section>
  </>;
}
