import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { STREAM_STYLE_KEY } from "../chat/streamStyle";
import { RevealMarkdown } from "../chat/MinimalChat";
import { STREAM_STYLES } from "../chat/streamStyle";
import { SettingsDialog } from "./SettingsDialog";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => { localStorage.clear(); document.body.innerHTML = ""; });

async function mount(node: React.ReactNode) {
  const el = document.createElement("div");
  document.body.append(el);
  const root = createRoot(el);
  await act(async () => root.render(node));
  return { el, root };
}

describe("Settings → Stream style", () => {
  it("lists the five styles with grok selected by default, and stores a new choice", async () => {
    await mount(<SettingsDialog open onClose={() => {}} tab="general" />);
    const radios = [...document.querySelectorAll<HTMLInputElement>('input[name="stream-style"]')];
    expect(radios.map((r) => r.value)).toEqual(["grok", "vscode", "chatgpt", "claude", "instant"]);
    expect(radios.find((r) => r.checked)?.value).toBe("grok");
    await act(async () => { radios.find((r) => r.value === "instant")!.click(); });
    expect(localStorage.getItem(STREAM_STYLE_KEY)).toBe("instant");
  });
});

describe("Settings (TAB-01)", () => {
  const tabs = () => [...document.querySelectorAll(".jg-sheet__tab")].map((t) => t.textContent!.replace(/[\uE000-\uF8FF›]/g, ""));
  it("opens Appearance first, groups panels, and hides panels with no backing capability", async () => {
    await mount(<SettingsDialog open onClose={() => {}} capabilities={{ voice: true, dictation: true, voiceChat: false }} />);
    expect(tabs()).toEqual(["Appearance", "General", "Voice & audio", "Agents", "Models & Providers", "Machine & devices", "Privacy & data", "About & diagnostics"]);
    expect([...document.querySelectorAll(".jg-sheet__group-title")].map((g) => g.textContent)).toEqual(["You", "Agents", "Connections", "Machine", "Privacy", "System"]);
    expect(document.querySelector(".jg-sheet__title")!.textContent).toBe("Appearance");
    const dark = document.querySelector<HTMLButtonElement>('[role="radiogroup"][aria-label="Theme"] [role="radio"]:nth-child(2)')!;
    await act(async () => { dark.click(); });
    expect(localStorage.getItem("aether-appearance")).toBe("dark");
  });
  it("accent color and icon pickers persist, keyboard arrows move the selection", async () => {
    await mount(<SettingsDialog open onClose={() => {}} />);
    const feel = document.querySelector<HTMLButtonElement>('[aria-label="Accent color"] [aria-checked="true"]')!;
    await act(async () => { feel.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true })); });
    expect(localStorage.getItem("appearance.feel")).toBe("shield-mono");
    expect(document.documentElement.dataset.feel).toBe("shield-mono");
    const icons = [...document.querySelectorAll<HTMLButtonElement>('[aria-label="App icon"] [role="radio"]')];
    await act(async () => { icons[1].click(); });
    expect(localStorage.getItem("appearance.icon")).toBe("shield-dark");
    expect(document.querySelector<HTMLLinkElement>('link[rel="icon"]')!.getAttribute("href")).toBe("/icon-shield-dark-512.png");
  });
  it("search finds rows and opens the right panel; Models & Providers has no key fields", async () => {
    await mount(<SettingsDialog open onClose={() => {}} />);
    const input = document.querySelector<HTMLInputElement>('input[aria-label="Search settings"]')!;
    const type = async (v: string) => act(async () => { const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!; set.call(input, v); input.dispatchEvent(new Event("input", { bubbles: true })); });
    for (const [q, label] of [["ollama", "Ollama"], ["sign in", "Subscription apps"], ["microphone", "Dictation"], ["theme", "Theme"], ["telemetry", "Where your data lives"]] as const) {
      await type(q);
      expect(document.querySelector(".jg-set-result")?.textContent).toContain(label);
    }
    await type("sign in");
    await act(async () => { input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
    expect(document.querySelector(".jg-sheet__title")!.textContent).toBe("Models & Providers");
    expect(document.querySelector('input[type="password"]')).toBeNull();
    expect(document.querySelector(".jg-sheet__page")!.textContent).not.toMatch(/API key:/);
    await type("zzzz");
    expect(document.body.textContent).toContain("No settings match");
  });
  it("legacy ids resolve to the new panels", async () => {
    const { parseSettingsRest } = await import("./SettingsDialog");
    expect(parseSettingsRest("providers")).toEqual({ tab: "models", segment: undefined });
    expect(parseSettingsRest("tools")).toEqual({ tab: "integrations", segment: "tools" });
    expect(parseSettingsRest("finance").tab).toBe("privacy");
    expect(parseSettingsRest("limits").tab).toBe("privacy");
    expect(parseSettingsRest("widgets").tab).toBe("appearance");
    expect(parseSettingsRest("reset").tab).toBe("about");
    expect(parseSettingsRest("nope")).toEqual({});
  });
  it("keeps search and the status footer in one inline Settings navigation and preserves compact push navigation", async () => {
    const width = vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(950);
    const view = await mount(<SettingsDialog inline open tab="appearance" onClose={() => {}} navigationFooter={<button>System status</button>} />);
    try {
      expect(view.el.querySelectorAll('nav[aria-label="Settings sections"]')).toHaveLength(1);
      expect(view.el.querySelector('.jg-set-navigation input[type="search"]')).toBeTruthy();
      expect(view.el.querySelector(".jg-set-navigation__footer")?.textContent).toBe("System status");
      await act(async () => view.root.render(<SettingsDialog inline open tab="appearance" navigationOpen={false} onClose={() => {}} />));
      expect(view.el.querySelector('nav[aria-label="Settings sections"]')).toBeNull();
      expect(view.el.querySelector("h1")?.textContent).toBe("Appearance");
      width.mockReturnValue(420);
      await act(async () => window.dispatchEvent(new Event("resize")));
      await act(async () => view.root.render(<SettingsDialog inline open navigationOpen={false} onClose={() => {}} />));
      expect(view.el.querySelector('nav[aria-label="Settings sections"]')).toBeTruthy();
      expect(view.el.querySelector(".jg-sheet__page")).toBeNull();
    } finally {
      await act(async () => view.root.unmount()); width.mockRestore();
    }
  });
});

describe("RevealMarkdown", () => {
  const links = { onOpen: () => {}, onCopy: () => {} };
  it("marks the grok entrance while live, and renders everything at once when not live", async () => {
    const { el } = await mount(<RevealMarkdown text={"Hello there"} live links={links} style={STREAM_STYLES.grok} />);
    const md = el.querySelector(".jg-md")!;
    expect(md.className).toContain("jg-md--enter-fade");
    expect(md.getAttribute("data-stream-style")).toBe("grok");
    const done = await mount(<RevealMarkdown text={"# Done\n\nAll text."} live={false} links={links} style={STREAM_STYLES.grok} />);
    expect(done.el.textContent).toContain("All text.");
    expect(done.el.querySelector(".jg-md")!.className).not.toContain("enter");
  });
  it("shows a caret only for caret styles while live", async () => {
    const { el } = await mount(<RevealMarkdown text="x" live links={links} style={STREAM_STYLES.chatgpt} />);
    expect(el.querySelector(".jg-caret")).toBeTruthy();
  });
});


it("text size control (Appearance) updates the live typography and remembers the device choice", async () => {
  await mount(<SettingsDialog open onClose={() => {}} />);
  const control = document.querySelector<HTMLSelectElement>('select[aria-label="Text size"]')!;
  await act(async () => { control.value = "20"; control.dispatchEvent(new Event("change", { bubbles: true })); });
  expect(localStorage.getItem("jaeger.ui.text-size")).toBe("20");
  expect(document.documentElement.style.getPropertyValue("--jg-font-size-base")).toBe("20px");
  expect(control.value).toBe("20");
  document.documentElement.removeAttribute("style");
});
