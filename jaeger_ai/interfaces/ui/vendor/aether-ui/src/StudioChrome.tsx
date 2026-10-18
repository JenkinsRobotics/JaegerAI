import { useEffect, useState } from "react";
import { AetherIcon } from "./AetherIcon";
import { Menu, MenuButton, type MenuItem } from "./Menu";
import { nextLayoutPreset, type LayoutPreset } from "./WorkspaceShell";

/* The three native Anima Studio header controls, ported faithfully from
 * `WorkspaceChrome.swift`: the studio-mode button (click cycles presets,
 * menu lists them), the workspace windows/tabs menu, and the appearance
 * toggle (System → Light → Dark). */

const PRESET_TITLE: Record<LayoutPreset, string> = { floating: "Floating", docked: "Docked", canvas: "Canvas" };

/** Native studio-mode button: colored per preset, primary click cycles,
 * right-click or ArrowDown opens the Studio modes menu with reset. */
export function StudioModeButton({ preset, onChange, extraItems = [], onExtraSelect }: { preset: LayoutPreset; onChange: (preset: LayoutPreset) => void; extraItems?: readonly MenuItem[]; onExtraSelect?: (id: string) => void }) {
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const title = PRESET_TITLE[preset];
  return (
    <>
      <button
        type="button"
        className={`aui-studio-mode aui-studio-mode--${preset}`}
        aria-label={`Studio mode: ${title}`}
        title={`Studio mode: ${title} · click to cycle`}
        aria-haspopup="menu"
        onClick={() => onChange(nextLayoutPreset(preset))}
        onContextMenu={(event) => { event.preventDefault(); setMenu({ x: event.clientX, y: event.clientY }); }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            const rect = event.currentTarget.getBoundingClientRect();
            setMenu({ x: rect.left, y: rect.bottom });
          }
        }}
      >
        <AetherIcon name={`mode-${preset}` as "mode-floating"} />
      </button>
      {menu ? (
        <Menu
          open
          anchor={menu}
          placement="bottom-start"
          ariaLabel="Studio modes"
          items={[
            ...(["floating", "docked", "canvas"] as const).map((entry) => ({
              id: entry,
              label: PRESET_TITLE[entry],
              icon: <AetherIcon name={`mode-${entry}` as "mode-floating"} />,
              kind: "radio" as const,
              checked: entry === preset,
            })),
            { id: "reset", label: "Reset Studio Layout", separatorBefore: true },
            ...extraItems,
          ]}
          onSelect={(id) => {
            setMenu(null);
            if (extraItems.some((item) => item.id === id)) onExtraSelect?.(id);
            else onChange(id === "reset" ? "floating" : (id as LayoutPreset));
          }}
          onClose={() => setMenu(null)}
        />
      ) : null}
    </>
  );
}

/** Native workspace windows/tabs menu. Browser-managed entries stay listed
 * but disabled, exactly as named in the native app. */
export function WorkspaceWindowMenu() {
  const browserManaged = "The browser manages windows and tabs.";
  return (
    <MenuButton
      label="Workspace windows and tabs"
      className="aui-workspace-windows"
      placement="bottom-end"
      items={[
        { id: "new-tab", label: "New Workspace Tab" },
        { id: "new-window", label: "New Workspace Window" },
        { id: "detach", label: "Detach Current Tab", disabled: true, disabledReason: browserManaged, separatorBefore: true },
        { id: "merge", label: "Merge All Windows", disabled: true, disabledReason: browserManaged },
        { id: "tab-bar", label: "Show or Hide Tab Bar", disabled: true, disabledReason: browserManaged },
        { id: "previous-tab", label: "Previous Workspace Tab", shortcut: "⇧⌘[", disabled: true, disabledReason: browserManaged, separatorBefore: true },
        { id: "next-tab", label: "Next Workspace Tab", shortcut: "⇧⌘]", disabled: true, disabledReason: browserManaged },
      ]}
      onSelect={(id) => {
        if (id === "new-tab") window.open(location.href, "_blank");
        if (id === "new-window") window.open(location.href, "_blank", "popup=yes,width=1280,height=800");
      }}
    >
      <AetherIcon name="windows" />
    </MenuButton>
  );
}

export type AppearanceMode = "system" | "light" | "dark";
const APPEARANCE_ORDER: readonly AppearanceMode[] = ["system", "light", "dark"];
const APPEARANCE_TITLE: Record<AppearanceMode, string> = { system: "System", light: "Light", dark: "Dark" };
const APPEARANCE_KEY = "aether-appearance";

function storedAppearance(): AppearanceMode {
  try {
    const saved = localStorage.getItem(APPEARANCE_KEY) as AppearanceMode | null;
    return saved && APPEARANCE_ORDER.includes(saved) ? saved : "system";
  } catch { return "system"; }
}

function applyAppearance(mode: AppearanceMode) {
  if (typeof document === "undefined") return;
  const prefersLight = typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: light)").matches;
  const light = mode === "light" || (mode === "system" && prefersLight);
  document.documentElement.classList.toggle("aether-light-theme", light);
  document.documentElement.dataset.appearance = mode;
}

const THEME_KEY = "aether-theme";

export interface AetherThemeManifest {
  id: string;
  name: string;
  modes: { dark: Record<string, string>; light: Record<string, string> };
}

/** Hot-installs a theme at runtime (VS Code-style): synthesizes the scoped
 * CSS from the manifest and injects it, replacing any prior install of the
 * same id. Pair with setAetherTheme(manifest.id) to activate immediately.
 * Build-time installs (dev/build-theme-css.mjs) produce identical selectors. */
export function installAetherTheme(manifest: AetherThemeManifest) {
  if (typeof document === "undefined") return;
  const vars = (tokens: Record<string, string>) =>
    Object.entries(tokens).map(([name, value]) => `  --aether-${name}: ${value};`).join("\n");
  const css = `.aether-theme-${manifest.id} {\n${vars(manifest.modes.dark)}\n}\n` +
    `.aether-theme-${manifest.id}.aether-light-theme,\n` +
    `.aether-theme-${manifest.id} .aether-home-theme.aether-light-theme,\n` +
    `.aether-theme-${manifest.id}.aether-light-theme .aether-home-theme {\n${vars(manifest.modes.light)}\n}`;
  const existing = document.head.querySelector(`style[data-aether-theme="${manifest.id}"]`);
  const style = existing ?? document.createElement("style");
  style.setAttribute("data-aether-theme", manifest.id);
  style.textContent = css;
  if (!existing) document.head.append(style);
}

/** Installed-theme selection (VS Code-style): themes generate side-by-side
 * scoped classes; this applies the persisted choice. "aether-default" (or
 * unset) means the built-in :root theme. */
export function setAetherTheme(themeID: string) {
  try { localStorage.setItem(THEME_KEY, themeID); } catch { /* device preference only */ }
  applyAetherTheme();
}

export function activeAetherTheme(): string {
  try { return localStorage.getItem(THEME_KEY) || "aether-default"; } catch { return "aether-default"; }
}

function applyAetherTheme() {
  if (typeof document === "undefined") return;
  const active = activeAetherTheme();
  const root = document.documentElement;
  for (const name of [...root.classList]) {
    if (name.startsWith("aether-theme-")) root.classList.remove(name);
  }
  if (active !== "aether-default") root.classList.add(`aether-theme-${active}`);
}

/* Suite-wide bootstrap: every page importing @aether/ui applies the stored
 * appearance at load, follows OS changes while in System mode, and follows
 * appearance changes made in any other open tab. */
if (typeof document !== "undefined") {
  applyAppearance(storedAppearance());
  applyAetherTheme();
  if (typeof matchMedia === "function") {
    matchMedia("(prefers-color-scheme: light)").addEventListener?.("change", () => {
      if (storedAppearance() === "system") applyAppearance("system");
    });
  }
  if (typeof window !== "undefined") {
    window.addEventListener("storage", (event) => {
      if (event.key === APPEARANCE_KEY) applyAppearance(storedAppearance());
      if (event.key === THEME_KEY) applyAetherTheme();
    });
  }
}

/** Native appearance toggle: cycles System → Light → Dark and applies
 * app-wide immediately; the choice persists per device. */
export function AppearanceToggle() {
  const [mode, setMode] = useState<AppearanceMode>(storedAppearance);
  useEffect(() => {
    const follow = (event: StorageEvent) => { if (event.key === APPEARANCE_KEY) setMode(storedAppearance()); };
    window.addEventListener("storage", follow);
    return () => window.removeEventListener("storage", follow);
  }, []);
  useEffect(() => {
    applyAppearance(mode);
    if (mode !== "system" || typeof matchMedia !== "function") return;
    const media = matchMedia("(prefers-color-scheme: light)");
    const follow = () => applyAppearance("system");
    media.addEventListener?.("change", follow);
    return () => media.removeEventListener?.("change", follow);
  }, [mode]);
  const title = APPEARANCE_TITLE[mode];
  return (
    <button
      type="button"
      className="aui-appearance-toggle"
      aria-label={`Appearance ${title}`}
      title={`Appearance: ${title} — click to change`}
      onClick={() => {
        const next = APPEARANCE_ORDER[(APPEARANCE_ORDER.indexOf(mode) + 1) % APPEARANCE_ORDER.length];
        try { localStorage.setItem(APPEARANCE_KEY, next); } catch { /* device preference only */ }
        setMode(next);
      }}
    >
      <AetherIcon name={`appearance-${mode}` as "appearance-system"} />
    </button>
  );
}
