import { describe, expect, it } from "vitest";
import { advance, initialReveal, step } from "./reveal";
import { resolveStreamStyle, STREAM_STYLES, STREAM_STYLE_IDS, type StreamStyleParams } from "./streamStyle";

const grok = STREAM_STYLES.grok;
const run = (text: string, params: StreamStyleParams, ticks: number, live = true) => {
  let s = initialReveal(0, 0);
  for (let i = 1; i <= ticks; i += 1) s = step(s, text, i * params.reveal.tickMs, params, live);
  return s;
};

describe("stream styles", () => {
  it("has the five presets, defaults to grok, and keeps the measured grok numbers", () => {
    expect(STREAM_STYLE_IDS.sort()).toEqual(["chatgpt", "claude", "grok", "instant", "vscode"]);
    expect(resolveStreamStyle(undefined).id).toBe("grok");
    expect(resolveStreamStyle("nope").id).toBe("grok");
    expect(grok.reveal).toMatchObject({ mode: "words", ratePerSec: 20, tickMs: 50, catchUp: "snap", adaptive: true });
    expect(grok.enter).toEqual({ kind: "fade", durationMs: 200, easing: "ease-out" });
    expect(grok.scroll).toEqual({ follow: "whenAtBottom", thresholdPx: 4, smooth: true });
    expect(grok.markdown.partialFence).toBe("live");
  });
});

describe("reveal engine", () => {
  it("counts words, chars and tokens; leading spaces aren't a unit", () => {
    expect(advance("one two three", 0, 2, "words")).toBe(8);
    expect(advance("one two", 3, 1, "words")).toBe(7);
    expect(advance("abcdef", 2, 3, "chars")).toBe(5);
    expect(advance("abcdefgh ij", 0, 1, "tokens")).toBe(4);
    expect(advance("abc", 0, 1, "raw")).toBe(3);
  });
  it("grok reveals one word per 50 ms tick (20 words/s) at the floor rate", () => {
    const text = "alpha beta gamma delta epsilon zeta eta theta";
    const slow = { ...grok, reveal: { ...grok.reveal, adaptive: false } };
    expect(text.slice(0, run(text, slow, 3).shown)).toBe("alpha beta gamma ");
  });
  it("adaptive pacing follows a faster incoming rate (floor stays)", () => {
    const text = "w ".repeat(400);
    let s = initialReveal(0, 0);
    s = step(s, text, 100, grok, true); // 800 chars in 100 ms → far above the floor
    const after = step(s, text, 150, grok, true);
    expect(after.shown - s.shown).toBeGreaterThan(2);
  });
  it("snaps when the backlog passes maxLagChars, and shows everything when the turn ends", () => {
    const big = "x ".repeat(1000);
    const snapped = step(initialReveal(0, 0), big, 50, grok, true);
    expect(big.length - snapped.shown).toBeLessThanOrEqual(grok.reveal.maxLagChars);
    expect(step(initialReveal(0, 0), "hello world", 50, grok, false).shown).toBe(11);
  });
  it("instant shows text exactly as it arrives", () => {
    expect(step(initialReveal(0, 0), "all of it at once", 10, STREAM_STYLES.instant, true).shown).toBe(17);
  });
  it("a rewrite that shortens the text never shows past its end", () => {
    const s = { ...initialReveal(0, 0), shown: 50, lastLen: 50 };
    expect(step(s, "short", 50, grok, true).shown).toBe(5);
  });
});
