import { describe, expect, it } from "vitest";
import type { ChatTurn } from "./host";
import { badge, messageCount, nextStickState, unreadSince } from "./scrollFollow";

const turn = (message: string, texts: string[]): ChatTurn =>
  ({ turnId: message, message, state: "complete", parts: texts.map((text) => ({ kind: "markdownContent", text })) });

describe("scroll follow", () => {
  it("counts user messages and non-empty assistant text blocks", () => {
    expect(messageCount([turn("hi", ["hello", ""]), turn("", ["note"])])).toBe(3);
  });
  it("reports unread only after leaving the bottom", () => {
    expect(unreadSince(null, 9)).toBe(0);
    expect(unreadSince(4, 9)).toBe(5);
    expect(unreadSince(9, 4)).toBe(0);
    expect(badge(120)).toBe("99+");
  });
  it("disengages immediately on upward momentum scroll even past raw touch window", () => {
    // Reproduces iOS Safari momentum scrolling / macOS scrollbar drag where userInputActive=false
    expect(nextStickState({
      prevScrollTop: 1200,
      scrollTop: 1080,
      gap: 120,
      thresholdPx: 64,
      isProgrammatic: false,
      userInputActive: false,
      wasSticking: true,
    })).toBe(false);
  });
  it("never disengages from our own programmatic followNow scroll", () => {
    expect(nextStickState({
      prevScrollTop: 1000,
      scrollTop: 950,
      gap: 120,
      thresholdPx: 64,
      isProgrammatic: true,
      userInputActive: false,
      wasSticking: true,
    })).toBe(true);
  });
  it("re-engages when reader returns near bottom", () => {
    expect(nextStickState({
      prevScrollTop: 900,
      scrollTop: 1180,
      gap: 20,
      thresholdPx: 64,
      isProgrammatic: false,
      userInputActive: false,
      wasSticking: false,
    })).toBe(true);
  });
});
