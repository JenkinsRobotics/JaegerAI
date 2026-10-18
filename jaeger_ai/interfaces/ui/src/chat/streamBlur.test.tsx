// IDE Chat grok preset: additive enter.blurPx (4) blurs each new block in with the fade; indicator 'avatar'
// draws our avatar progress row.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ProgressLine, RevealMarkdown } from "./MinimalChat";
import { STREAM_STYLES } from "./streamStyle";
import { readFileSync } from "node:fs";
const css = readFileSync(`${process.cwd()}/src/chat/chat.css`, "utf8");

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let el: HTMLDivElement; let root: Root;
beforeEach(() => { el = document.createElement("div"); document.body.append(el); root = createRoot(el); });
afterEach(() => { act(() => root.unmount()); el.remove(); });

describe("grok stream preset", () => {
  it("passes blurPx to the entrance as --jg-enter-blur; other presets get 0", async () => {
    await act(async () => { root.render(<RevealMarkdown text="Hello there" live links={{} as never} style={STREAM_STYLES.grok} />); });
    expect(el.querySelector<HTMLElement>(".jg-md--enter-fade")!.style.getPropertyValue("--jg-enter-blur")).toBe("4px");
    await act(async () => { root.render(<RevealMarkdown text="Hello there" live links={{} as never} style={STREAM_STYLES.chatgpt} />); });
    expect(el.querySelector<HTMLElement>(".jg-md")!.style.getPropertyValue("--jg-enter-blur")).toBe("0px");
  });
  it("animates blur → 0 in the entrance keyframes, and reduced motion turns the entrance off", () => {
    expect(css).toMatch(/@keyframes jg-stream-enter \{ from \{[^}]*filter: blur\(var\(--jg-enter-blur/);
    expect(css).toMatch(/prefers-reduced-motion: reduce\) \{ \.jg-md--enter-fade > \*[^}]*animation: none/);
  });
  it("indicator 'avatar' renders our avatar progress row", async () => {
    expect(STREAM_STYLES.grok.indicator.kind).toBe("avatar");
    await act(async () => { root.render(<ProgressLine phrase="Thinking" agent={{ id: "native:jaeger", name: "Jaeger" }} />); });
    expect(el.querySelector(".jg-progress-line .jg-progress-avatar")).toBeTruthy();
  });
});
