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
