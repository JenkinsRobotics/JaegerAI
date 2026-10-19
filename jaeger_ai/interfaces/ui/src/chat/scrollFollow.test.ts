import { describe, expect, it } from "vitest";
import type { ChatTurn } from "./host";
import { badge, messageCount, unreadSince } from "./scrollFollow";

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
});
