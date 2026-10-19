/* Settings (⌘, or the account chip): a full in-window sheet laid out like Grok's (final-check/grok-settings.png):
 * a left sidebar of tabs with icons, a titled page of sections, each a card of rows (label left, control right),
 * a close button top-right. Only settings Jaeger really has: Theme (Aether's aether-appearance), Stream style
 * (streamStyle.ts, per device), file uploads (composer BYTES_UPLOAD_FLAG); Voice and Connection are read-only
 * status. Esc / a click outside / ⌘, again close it (popup coordinator). Icons: codicons (MIT). */
import { useState, type ReactNode } from "react";
import { useExclusivePopup } from "../popups/coordinator";
import { Icon, type IconName } from "../icons/Icon";
import { setStreamStyle, STREAM_STYLE_IDS, STREAM_STYLE_LABELS, useStreamStyle } from "../chat/streamStyle";
import { BYTES_UPLOAD_FLAG, bytesUploadEnabled } from "../chat/composer";
import type { HostCapabilities } from "../chat/hostH8";

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
}

type Tab = "general" | "voice" | "connection" | "about";
const TABS: { id: Tab; label: string; icon: IconName }[] = [
  { id: "general", label: "General", icon: "settings-gear" },
  { id: "voice", label: "Voice", icon: "mic" },
  { id: "connection", label: "Connection", icon: "server" },
  { id: "about", label: "About", icon: "info" },
];

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="jg-sheet__section"><h3 className="jg-sheet__section-title">{title}</h3><div className="jg-sheet__card">{children}</div></section>;
}
function Row({ label, hint, children }: { label: string; hint?: string; children?: ReactNode }) {
  return <div className="jg-sheet__row"><span className="jg-sheet__row-label">{label}{hint && <span className="jg-sheet__hint">{hint}</span>}</span>{children}</div>;
}
function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return <button type="button" role="switch" aria-label={label} aria-checked={checked} className={`jg-switch${checked ? " is-on" : ""}`} onClick={() => onChange(!checked)}><span /></button>;
}

export function SettingsDialog({ open, onClose, capabilities, gateway }: {
  open: boolean; onClose: () => void; capabilities?: HostCapabilities; gateway?: string;
}) {
  const [tab, setTab] = useState<Tab>("general");
  const [appearance, setAppearance] = useState<Appearance>(storedAppearance);
  const [uploads, setUploads] = useState(bytesUploadEnabled);
  const current = useStreamStyle().id;
  useExclusivePopup(open, onClose);
  if (!open) return null;
  const title = TABS.find((t) => t.id === tab)!.label;
  const yes = (v?: boolean) => (v ? "Available" : "Not available");
  return (
    <div className="jg-sheet__scrim" onMouseDown={onClose}>
      <div className="jg-sheet" role="dialog" aria-modal aria-label="Settings" onMouseDown={(e) => e.stopPropagation()}>
        <nav className="jg-sheet__nav" aria-label="Settings sections">
          {TABS.map((t) => (
            <button key={t.id} type="button" className={`jg-sheet__tab${t.id === tab ? " is-active" : ""}`} aria-current={t.id === tab ? "page" : undefined} onClick={() => setTab(t.id)}>
              <Icon name={t.icon} size={15} />{t.label}
            </button>
          ))}
        </nav>
        <div className="jg-sheet__page">
          <button type="button" className="jg-sheet__close" aria-label="Close settings" onClick={onClose}><Icon name="close" size={16} /></button>
          <h2 className="jg-sheet__title">{title}</h2>
          {tab === "general" && <>
            <Section title="Appearance">
              <Row label="Theme">
                <select className="jg-sheet__select" aria-label="Theme" value={appearance}
                  onChange={(e) => { const m = e.target.value as Appearance; setAppearance(m); applyAppearance(m); }}>
                  <option value="system">Follow System</option><option value="light">Light</option><option value="dark">Dark</option>
                </select>
              </Row>
            </Section>
            <Section title="Chat">
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
              <Row label="Send file contents with messages" hint="Off sends only file names.">
                <Toggle label="Send file contents with messages" checked={uploads}
                  onChange={(v) => { setUploads(v); try { localStorage.setItem(BYTES_UPLOAD_FLAG, v ? "1" : "0"); } catch { /* */ } }} />
              </Row>
            </Section>
          </>}
          {tab === "voice" && <Section title="This device">
            <Row label="Dictation"><span className="jg-sheet__value">{yes(capabilities?.dictation ?? capabilities?.voice)}</span></Row>
            <Row label="Voice chat"><span className="jg-sheet__value">{yes(capabilities?.voiceChat ?? capabilities?.voice)}</span></Row>
          </Section>}
          {tab === "connection" && <Section title="Gateway">
            <Row label="Address"><span className="jg-sheet__value">{gateway ?? (typeof location !== "undefined" ? location.origin : "")}</span></Row>
            <Row label="Token" hint="Held by the server, never by this page."><span className="jg-sheet__value">Server-side</span></Row>
          </Section>}
          {tab === "about" && <Section title="Jaeger AI">
            <Row label="App"><span className="jg-sheet__value">Jaeger AI</span></Row>
            <Row label="Icons"><span className="jg-sheet__value">VS Code Codicons (MIT)</span></Row>
          </Section>}
        </div>
      </div>
    </div>
  );
}
