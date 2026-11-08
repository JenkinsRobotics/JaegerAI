/* Settings (TAB-01, 2026-10-31): 13 panels in 6 groups, Appearance first, search (⌘F or /), roving keyboard nav,
 * one PageHeader (h1) per panel, push navigation on compact widths. Originally:
 * Settings (⌘, or the account chip): a full in-window sheet laid out like Grok's (final-check/grok-settings.png):
 * a left sidebar of tabs with icons, a titled page of sections, each a card of rows (label left, control right),
 * a close button top-right. Only settings Jaeger really has: device typography, Theme (Aether's aether-appearance), Stream style
 * (streamStyle.ts, per device), file uploads (composer BYTES_UPLOAD_FLAG); Voice and Connection are read-only
 * status. Esc / a click outside / ⌘, again close it (popup coordinator). Icons: codicons (MIT). */
import { AudioSettingsPanel } from "./AudioSettingsPanel";
import {DevicePreferencesPanel} from "./DevicePreferencesPanel";
import { ProvidersPanel } from "./ProvidersPanel";
import { cloneElement, isValidElement, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactElement, type ReactNode } from "react";
import { useExclusivePopup } from "../popups/coordinator";
import { Icon, type IconName } from "../icons/Icon";
import { setStreamStyle, STREAM_STYLE_IDS, STREAM_STYLE_LABELS, useStreamStyle } from "../chat/streamStyle";
import { BYTES_UPLOAD_FLAG, bytesUploadEnabled } from "../chat/composer";
import type { HostCapabilities } from "../chat/hostH8";

import { GROUPS, LEGACY_SETTINGS, PANEL_LABEL, search as searchSettings, type PanelId } from "./registry";
import { AppearancePanel } from "./AppearancePanel";
import { syncThemeColor } from "./appearance";
import { PageHeader } from "../components/PageHeader";
import { useSizeClass } from "../shell/breakpoints";
import { navigate } from "../shell/router";

const HINT: Record<string, string> = {
  grok: "Words flow in with a soft fade, like Grok.",
  instant: "Text appears exactly as it arrives, no smoothing.",
};

export type Appearance = "system" | "light" | "dark";
const APPEARANCE_KEY = "aether-appearance";
export function storedAppearance(): Appearance {
  try { const v = localStorage.getItem(APPEARANCE_KEY); return v === "light" || v === "dark" ? v : "system"; } catch { return "system"; }
}
/** Same storage key and root class Aether's AppearanceToggle uses (vendor/aether-ui StudioChrome), set directly. */
export function applyAppearance(mode: Appearance) {
  try { localStorage.setItem(APPEARANCE_KEY, mode); } catch { /* storage unavailable */ }
  const prefersLight = typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: light)").matches;
  document.documentElement.classList.toggle("aether-light-theme", mode === "light" || (mode === "system" && prefersLight));
  document.documentElement.dataset.appearance = mode;
  try { syncThemeColor(); } catch { /* no DOM styles (tests) */ }
}

export type Tab = PanelId;
const ICON: Record<PanelId, IconName> = {
  checkpoints: "history", widgets: "settings-gear", appearance: "symbol-color", general: "settings-gear", voice: "mic", notifications: "comment", agents: "account", memory: "history",
  integrations: "link", models: "server", automations: "rocket", machine: "terminal", privacy: "eye-closed", limits: "pass", about: "info",
};
/** Kept for callers that list the groups (Home index etc.). */
export const SETTINGS_GROUPS = GROUPS.map((g) => ({ id: g.id, label: g.label, tabs: g.panels }));
const ALL = GROUPS.flatMap((g) => g.panels);
export const isSettingsTab = (v: string | undefined): v is Tab => !!v && (ALL as string[]).includes(v);
/** "/settings/<rest>" → panel + optional segment (legacy ids resolve too). */
export function parseSettingsRest(rest: string | undefined): { tab?: Tab; segment?: string } {
  const [head, seg] = (rest ?? "").split("/");
  const mapped = head && LEGACY_SETTINGS[head] ? LEGACY_SETTINGS[head].split("/") : [head, seg];
  return isSettingsTab(mapped[0]) ? { tab: mapped[0], segment: mapped[1] ?? seg } : {};
}

function Section({ title, anchor, children }: { title: string; anchor?: string; children: ReactNode }) {
  return <section className="jg-sheet__section" id={anchor ? `set-${anchor}` : undefined}><h3 className="jg-sheet__section-title">{title}</h3><div className="jg-sheet__card">{children}</div></section>;
}
function Row({ label, hint, anchor, children }: { label: string; hint?: string; anchor?: string; children?: ReactNode }) {
  return <div className="jg-sheet__row" id={anchor ? `set-${anchor}` : undefined}><span className="jg-sheet__row-label">{label}{hint && <span className="jg-sheet__hint">{hint}</span>}</span>{children}</div>;
}
function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return <button type="button" role="switch" aria-label={label} aria-checked={checked} className={`jg-switch${checked ? " is-on" : ""}`} onClick={() => onChange(!checked)}><span /></button>;
}
const Anchor = ({ id, children }: { id: string; children: ReactNode }) => <div id={`set-${id}`} className="jg-set-anchor">{children}</div>;

export function SettingsDialog({ inline, tab: controlledTab, segment, onTab, resetPanel, open, onClose, gateway, agentsPanel, automationsPanel, skillsPanel, libraryPanel, toolsPanel, diagnosticsPanel, workflowsPanel, channelsPanel, notificationsPanel, memoryPanel, requestedTab, updatesPanel, clipboardPanel, computerPanel, financePanel, integrationsPanel, modelsContent, integrationsExtras, checkpointsPanel, widgetsPanel }: {
  /** Render as a page (the /settings route) instead of a modal sheet. */ inline?: boolean; tab?: Tab; segment?: string; onTab?: (tab: Tab | "") => void; resetPanel?: ReactNode;
  integrationsPanel?: ReactNode; modelsContent?: ReactNode; integrationsExtras?: ReactNode; checkpointsPanel?: ReactNode; widgetsPanel?: ReactNode;
  financePanel?:ReactNode;computerPanel?:ReactNode;clipboardPanel?:ReactNode;updatesPanel?:ReactNode;requestedTab?:{tab:Tab;sequence:number}; open: boolean; onClose: () => void; capabilities?: HostCapabilities; gateway?: string; agentsPanel?: ReactNode; automationsPanel?: ReactNode; skillsPanel?: ReactNode; libraryPanel?: ReactNode; toolsPanel?: ReactNode; diagnosticsPanel?: ReactNode; workflowsPanel?: ReactNode; channelsPanel?: ReactNode; notificationsPanel?: ReactNode; memoryPanel?:ReactNode;
}) {
  const [ownTab, setOwnTab] = useState<Tab>("appearance");
  const tab = controlledTab ?? ownTab;
  const setTab = (next: Tab) => { setOwnTab(next); onTab?.(next); };
  useEffect(()=>{if(open&&requestedTab)setTab(requestedTab.tab);},[open,requestedTab]);
  const [appearance, setAppearance] = useState<Appearance>(storedAppearance);
  useEffect(() => {
    applyAppearance(appearance);
    if (appearance !== "system" || typeof matchMedia !== "function") return;
    const media = matchMedia("(prefers-color-scheme: light)");
    const sync = () => applyAppearance("system");
    media.addEventListener?.("change", sync);
    return () => media.removeEventListener?.("change", sync);
  }, [appearance]);
  const [uploads, setUploads] = useState(bytesUploadEnabled);
  const current = useStreamStyle().id;
  const [q, setQ] = useState("");
  const [flash, setFlash] = useState<string>();
  const [autoSeg, setAutoSeg] = useState<string>();
  const root = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const { cls, short } = useSizeClass(root);
  const compact = cls === "compact";
  useExclusivePopup(open && !inline, onClose);
  const available = (id: Tab) => (id !== "checkpoints" || !!checkpointsPanel) && (id !== "widgets" || !!widgetsPanel) && (id !== "limits" || !!financePanel) && (id !== "memory" || !!(memoryPanel || skillsPanel || libraryPanel)) && (id !== "notifications" || !!notificationsPanel)
    && (id !== "automations" || !!(automationsPanel || workflowsPanel || channelsPanel)) && (id !== "integrations" || !!(integrationsPanel || toolsPanel));
  const results = useMemo(() => searchSettings(q, available), [q, financePanel, memoryPanel, skillsPanel, libraryPanel, notificationsPanel, automationsPanel, workflowsPanel, channelsPanel, integrationsPanel]); // eslint-disable-line react-hooks/exhaustive-deps
  // ⌘F or / focuses search; Esc clears it.
  useEffect(() => {
    if (!open && !inline) return;
    const key = (e: globalThis.KeyboardEvent) => {
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target as HTMLElement)?.tagName ?? "");
      if ((e.metaKey && e.key.toLowerCase() === "f") || (e.key === "/" && !typing)) { e.preventDefault(); searchRef.current?.focus(); searchRef.current?.select(); }
      if (e.metaKey && e.key === "[" && compact && controlledTab) { e.preventDefault(); onTab?.(""); }
    };
    window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key);
  }, [open, inline, compact, controlledTab, onTab]);
  useEffect(() => {
    if (!flash) return;
    const el = document.getElementById(`set-${flash}`);
    el?.scrollIntoView?.({ block: "nearest" }); el?.setAttribute("data-flash", "");
    const t = window.setTimeout(() => { el?.removeAttribute("data-flash"); setFlash(undefined); }, 600);
    return () => window.clearTimeout(t);
  }, [flash, tab]);
  if (!open && !inline) return null;
  const openResult = (panel: Tab, anchor: string) => { setQ(""); setTab(panel); if (panel === "integrations" || panel === "automations" || panel === "models") setAutoSeg(anchor); setFlash(anchor); };
  const navKey = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Home" && e.key !== "End") return;
    const items = [...(navRef.current?.querySelectorAll<HTMLButtonElement>(".jg-sheet__tab") ?? [])];
    const i = items.indexOf(document.activeElement as HTMLButtonElement);
    const n = e.key === "Home" ? 0 : e.key === "End" ? items.length - 1 : (i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    e.preventDefault(); items[n]?.focus();
  };
  const seg = autoSeg ?? segment;
  const embedded = !inline;
  const header = (title: string, subtitle?: string) => <PageHeader title={title} subtitle={short ? undefined : subtitle} embedded={embedded}
    back={inline && compact ? { label: "Settings", onBack: () => onTab?.("") } : undefined} />;
  const showList = !(inline && compact) || !controlledTab;
  const showPanel = !(inline && compact) || !!controlledTab;
  const integ = isValidElement(integrationsPanel) ? cloneElement(integrationsPanel as ReactElement<{ embedded?: boolean; initialTab?: string; back?: { label: string; onBack: () => void } }>, { embedded, initialTab: seg === "tools" || seg === "apps" || seg === "servers" ? seg : undefined, back: inline && compact ? { label: "Settings", onBack: () => onTab?.("") } : undefined }) : integrationsPanel;
  return (
    <div ref={root} className={inline ? "jg-sheet__inline" : "jg-sheet__scrim"} data-size={cls} onMouseDown={inline ? undefined : onClose}>
      <div className={`jg-sheet${inline ? " jg-sheet--inline" : ""}`} data-view={inline && compact ? (controlledTab ? "panel" : "list") : "split"} role={inline ? "region" : "dialog"} aria-modal={inline ? undefined : true} aria-label="Settings" onMouseDown={(e) => e.stopPropagation()}>
        {showList && <nav ref={navRef} className="jg-sheet__nav" aria-label="Settings sections" onKeyDown={navKey}>
          {inline && compact && <h1 className="jg-set-list-title">Settings</h1>}
          <div className="jg-set-search">
            <input ref={searchRef} type="search" className="jg-set-search__input" placeholder="Search settings" aria-label="Search settings" value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Escape") { if (q) { e.preventDefault(); e.stopPropagation(); setQ(""); } else (e.target as HTMLInputElement).blur(); } if (e.key === "Enter" && results[0]) openResult(results[0].panel, results[0].anchor); if (e.key === "ArrowDown") { e.preventDefault(); navRef.current?.querySelector<HTMLButtonElement>(".jg-sheet__tab")?.focus(); } }} />
            <kbd aria-hidden="true">⌘F</kbd>
          </div>
          {q ? <div className="jg-sheet__group" role="group" aria-label="Search results">
            <h4 className="jg-sheet__group-title" role="status">{results.length ? `${results.length} result${results.length === 1 ? "" : "s"}` : `No settings match “${q}”`}</h4>
            {results.map((r) => <button key={r.id} type="button" className="jg-sheet__tab jg-set-result" onClick={() => openResult(r.panel, r.anchor)}>
              <span><b>{r.label}</b><small>{GROUPS.find((g) => g.panels.includes(r.panel))?.label} › {PANEL_LABEL[r.panel]}</small></span></button>)}
          </div> : GROUPS.map((group) => {
            const tabs = group.panels.filter(available);
            if (!tabs.length) return null;
            return <div key={group.id} className="jg-sheet__group" role="group" aria-label={group.label}>
              <h4 className="jg-sheet__group-title">{group.label}</h4>
              {tabs.map((t) => (
                <button key={t} type="button" className={`jg-sheet__tab${t === tab ? " is-active" : ""}`} aria-current={t === tab ? "page" : undefined} tabIndex={t === tab ? 0 : -1} onClick={() => { setAutoSeg(undefined); setTab(t); }}>
                  <Icon name={ICON[t]} size={15} />{PANEL_LABEL[t]}{inline && compact && <span className="jg-set-chev" aria-hidden="true">›</span>}
                </button>
              ))}
            </div>;
          })}
        </nav>}
        {showPanel && <div className="jg-sheet__page">
          {!inline && <button type="button" className="jg-sheet__close" aria-label="Close settings" onClick={onClose}><Icon name="close" size={16} /></button>}
          {!inline && <h2 className="jg-sheet__title">{PANEL_LABEL[tab]}</h2>}
          {tab === "appearance" && <>{header("Appearance", "Theme, feel, app icon and text.")}<AppearancePanel appearance={appearance} onAppearance={(m) => { setAppearance(m); applyAppearance(m); }} Row={Row} Section={Section} /></>}
          {tab === "general" && <>{header("General", "How chat behaves on this device.")}
            <Anchor id="device"><DevicePreferencesPanel/></Anchor>
            <Section title="Chat" anchor="stream-style">
              <fieldset className="jg-sheet__radios">
                <legend className="jg-sheet__row-label">Stream style</legend>
                {STREAM_STYLE_IDS.map((id) => (
                  <label key={id} className={`jg-settings__option${id === current ? " is-selected" : ""}`}>
                    <input type="radio" name="stream-style" value={id} checked={id === current} onChange={() => setStreamStyle(id)} />
                    <span className="jg-settings__name">{STREAM_STYLE_LABELS[id]}</span>
                    {HINT[id] && <span className="jg-settings__hint">{HINT[id]}</span>}
                  </label>
                ))}
              </fieldset>
            </Section>
          </>}
          {tab === "agents" && <>{header("Agents", "Your agents, primary agent and pins.")}<Anchor id="agents">{agentsPanel ?? <p>Agent management is not available from this host.</p>}</Anchor></>}
          {tab === "models" && <>{header("Models & Providers", "Sign-in and status for the apps and local models Jaeger runs. No API keys.")}<Anchor id="cli"><ProvidersPanel /></Anchor><span id="set-ollama" />{modelsContent}</>}
          {tab === "integrations" && <>{integ ?? toolsPanel}{integrationsExtras}</>}
          {tab === "checkpoints" && checkpointsPanel}
          {tab === "widgets" && widgetsPanel}
          {tab === "memory" && <>{header("Memory & skills")}
            {memoryPanel && <Section title="Memory" anchor="memory">{memoryPanel}</Section>}
            {skillsPanel && <Section title="Skills" anchor="skills">{skillsPanel}</Section>}
            {libraryPanel && <Section title="Library" anchor="library">{libraryPanel}</Section>}</>}
          {tab === "notifications" && <>{header("Notifications")}<Anchor id="notifications">{notificationsPanel}</Anchor></>}
          {tab === "automations" && <AutomationsTabs header={header("Automations", "Schedules, webhooks, workflows and channels.")} initial={seg} panels={{ automations: automationsPanel, workflows: workflowsPanel, channels: channelsPanel }} />}
          {tab === "limits" && <>{header("Spending limits", "What agents may spend, and when they must ask.")}<Anchor id="limits">{financePanel}</Anchor></>}
          {tab === "privacy" && <>{header("Privacy & data", "What leaves this device.")}
            <Section title="Files" anchor="uploads">
              <Row label="Send file contents with messages" hint="Off sends only file names.">
                <Toggle label="Send file contents with messages" checked={uploads}
                  onChange={(v) => { setUploads(v); try { localStorage.setItem(BYTES_UPLOAD_FLAG, v ? "1" : "0"); } catch { /* */ } }} />
              </Row>
            </Section>
            <Section title="Where your data lives" anchor="storage">
              <Row label="WebUI state" hint="Documents, Studio, avatars, research jobs and settings files."><span className="jg-sheet__value">On this Mac, ~/.jaeger</span></Row>
              <Row label="This browser" hint="Theme, feel, icon, panel layout and drafts."><span className="jg-sheet__value">This device only</span></Row>
            </Section>
          </>}
          {tab === "machine" && <>{header("Machine & devices", "This Mac: computer control, clipboard and the gateway.")}
            <Section title="This Mac" anchor="computer">
              {computerPanel}
              <span id="set-clipboard" />{clipboardPanel}
              <Row label="Hardware and telemetry" hint="Live CPU, GPU, memory and jobs."><button type="button" className="jg-u-btn" onClick={() => navigate("/machine")}>Open Machine</button></Row>
            </Section>
            <Section title="Gateway" anchor="gateway">
              <Row label="Application API address" hint="Read-only. The backend owns Gateway routing and authentication."><span className="jg-sheet__value">{gateway ?? (typeof location !== "undefined" ? location.origin : "")}</span></Row>
              <Row label="Token" hint="Held by the server, never by this page."><span className="jg-sheet__value">Server-side</span></Row>
            </Section>
          </>}
          {tab === "voice" && <>{header("Voice & audio")}<Section title="This device" anchor="dictation"><AudioSettingsPanel /></Section></>}
          {tab === "about" && <>{header("About & diagnostics")}
            <Section title="Jaeger AI" anchor="version">
              {updatesPanel}
              <Row label="App"><span className="jg-sheet__value">Jaeger AI</span></Row>
              <Row label="Icons"><span className="jg-sheet__value">Jaeger house icons, VS Code Codicons (MIT)</span></Row>
            </Section>
            {diagnosticsPanel && <Section title="Diagnostics" anchor="diagnostics">{diagnosticsPanel}</Section>}
            {resetPanel && <section className="jg-sheet__section jg-set-danger" id="set-reset"><h3 className="jg-sheet__section-title">Danger zone</h3>{resetPanel}</section>}
          </>}
        </div>}
      </div>
    </div>
  );
}

function AutomationsTabs({ header, initial, panels }: { header: ReactNode; initial?: string; panels: Record<"automations" | "workflows" | "channels", ReactNode> }) {
  const opts = (["automations", "workflows", "channels"] as const).filter((k) => panels[k]);
  const label = { automations: "Schedules & webhooks", workflows: "Workflows", channels: "Channels" } as const;
  const [cur, setCur] = useState<(typeof opts)[number]>(opts.includes(initial as never) ? (initial as (typeof opts)[number]) : opts[0]);
  useEffect(() => { if (opts.includes(initial as never)) setCur(initial as (typeof opts)[number]); }, [initial]); // eslint-disable-line react-hooks/exhaustive-deps
  return <>{header}
    {opts.length > 1 && <div role="tablist" aria-label="Automations" className="jg-set-seg jg-set-seg--tabs">
      {opts.map((k) => <button key={k} type="button" role="tab" aria-selected={cur === k} className="jg-set-tile" data-on={cur === k || undefined} onClick={() => setCur(k)}>{label[k]}</button>)}
    </div>}
    <div id={`set-${cur}`} className="jg-set-anchor">{panels[cur]}</div>
  </>;
}
