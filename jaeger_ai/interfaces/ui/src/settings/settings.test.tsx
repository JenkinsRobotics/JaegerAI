import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
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
    await mount(<SettingsDialog open onClose={() => {}} />);
    const radios = [...document.querySelectorAll<HTMLInputElement>('input[name="stream-style"]')];
    expect(radios.map((r) => r.value)).toEqual(["grok", "vscode", "chatgpt", "claude", "instant"]);
    expect(radios.find((r) => r.checked)?.value).toBe("grok");
    await act(async () => { radios.find((r) => r.value === "instant")!.click(); });
    expect(localStorage.getItem(STREAM_STYLE_KEY)).toBe("instant");
    expect(document.querySelector<HTMLInputElement>('input[value="instant"]')!.checked).toBe(true);
  });
});

describe("Settings sheet", () => {
  it("has Grok's sidebar of tabs, switches pages, and only real settings (theme, stream style, uploads)", async () => {
    await mount(<SettingsDialog open onClose={() => {}} capabilities={{ voice: true, dictation: true, voiceChat: false }} />);
    const tabs = [...document.querySelectorAll(".jg-sheet__tab")].map((t) => t.textContent!.replace(/[\uE000-\uF8FF]/g, ""));
    expect(tabs).toEqual(["General", "Agents", "Voice", "Connection", "About"]);
    const theme = document.querySelector<HTMLSelectElement>('select[aria-label="Theme"]')!;
    await act(async () => { theme.value = "dark"; theme.dispatchEvent(new Event("change", { bubbles: true })); });
    expect(localStorage.getItem("aether-appearance")).toBe("dark");
    await act(async () => { document.querySelector<HTMLButtonElement>('[role="switch"]')!.click(); });
    expect(localStorage.getItem("jaeger.ui.bytes-upload")).toBe("0");
    await act(async () => { (document.querySelectorAll<HTMLButtonElement>(".jg-sheet__tab")[2]).click(); });
    expect(document.querySelector(".jg-sheet__title")!.textContent).toBe("Voice");
    expect(document.body.textContent).toContain("Not available");
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


it("text size control updates the live typography and remembers the device choice", async () => {
  await mount(<SettingsDialog open onClose={() => {}} />);
  const control = document.querySelector<HTMLSelectElement>('select[aria-label="Text size"]')!;
  await act(async () => { control.value = "20"; control.dispatchEvent(new Event("change", { bubbles: true })); });
  expect(localStorage.getItem("jaeger.ui.text-size")).toBe("20");
  expect(document.documentElement.style.getPropertyValue("--jg-font-size-base")).toBe("20px");
  expect(control.value).toBe("20");
  document.documentElement.removeAttribute("style");
});
