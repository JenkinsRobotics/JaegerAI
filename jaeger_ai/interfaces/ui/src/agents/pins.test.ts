import { beforeEach, describe, expect, it } from "vitest";
import type { SidebarRow } from "./agentsLogic";
import { MAX_PINS, PINS_KEY, loadPins, pin, savePins, splitPinned, unpin } from "./pins";

const row = (id: string) => ({ agent: { id, name: id }, lastActivityAt: 0 }) as unknown as SidebarRow;

describe("pinned agents", () => {
  beforeEach(() => localStorage.clear());

  it("pins at the end or at an index, moves an already pinned agent, caps the count", () => {
    expect(pin([], "a")).toEqual(["a"]);
    expect(pin(["a", "b"], "c", 1)).toEqual(["a", "c", "b"]);
    expect(pin(["a", "b", "c"], "a", 2)).toEqual(["b", "c", "a"]);
    expect(pin(["a"], "b", -3)).toEqual(["b", "a"]);
    const many = Array.from({ length: MAX_PINS }, (_, i) => `x${i}`);
    expect(pin(many, "new")).toHaveLength(MAX_PINS);
    expect(unpin(["a", "b"], "a")).toEqual(["b"]);
  });

  it("splits specialists into pinned tiles (pin order) and the rest; unknown ids are ignored", () => {
    const { pinned, rest } = splitPinned([row("a"), row("b"), row("c")], ["c", "gone", "a"]);
    expect(pinned.map((r) => r.agent.id)).toEqual(["c", "a"]);
    expect(rest.map((r) => r.agent.id)).toEqual(["b"]);
  });

  it("persists per device and survives bad storage", () => {
    savePins(["a", "b"]);
    expect(loadPins()).toEqual(["a", "b"]);
    localStorage.setItem(PINS_KEY, "{not json");
    expect(loadPins()).toEqual([]);
    localStorage.setItem(PINS_KEY, JSON.stringify(["a", 3, null]));
    expect(loadPins()).toEqual(["a"]);
  });
});
