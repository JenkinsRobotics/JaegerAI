import { describe, expect, it } from "vitest";
import { HOME_PANELS, loadPanels, movePanel } from "./homeLayout";

describe("home panel layout", () => {
  it("falls back to defaults and appends new panels", () => {
    expect(loadPanels({ getItem: () => null })).toEqual([...HOME_PANELS]);
    expect(loadPanels({ getItem: () => '["disk","bogus"]' })[0]).toBe("disk");
    expect(loadPanels({ getItem: () => '["disk"]' })).toHaveLength(HOME_PANELS.length);
    expect(loadPanels({ getItem: () => "{bad" })).toEqual([...HOME_PANELS]);
  });
  it("moves a panel", () => {
    const o = movePanel([...HOME_PANELS], "recent", 0);
    expect(o[0]).toBe("recent");
    expect(o).toHaveLength(HOME_PANELS.length);
  });
});
