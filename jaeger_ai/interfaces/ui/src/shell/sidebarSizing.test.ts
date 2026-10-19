import { describe, expect, it } from "vitest";
import {
  SIDEBAR, autoCollapses, clampWidth, defaultPrefs, dragTo, keyAdjust, layout, parsePrefs, serializePrefs, toggle,
} from "./sidebarSizing";

describe("sidebar sizing", () => {
  it("clamps to 240–400 and rounds", () => {
    expect(clampWidth(100)).toBe(240);
    expect(clampWidth(999)).toBe(400);
    expect(clampWidth(301.6)).toBe(302);
    expect(clampWidth(Number.NaN)).toBe(280);
  });

  it("collapses to the rail when dragged below 210, keeping the expanded width", () => {
    const p = { expandedWidth: 320, isCollapsed: false };
    expect(dragTo(p, 209)).toEqual({ expandedWidth: 320, isCollapsed: true });
    expect(dragTo(p, 215)).toEqual({ expandedWidth: 240, isCollapsed: false });
    expect(dragTo({ expandedWidth: 320, isCollapsed: true }, 360)).toEqual({ expandedWidth: 360, isCollapsed: false });
    expect(dragTo(p, 520)).toEqual({ expandedWidth: 400, isCollapsed: false });
  });

  it("auto-collapses while the window is narrower than width + 424", () => {
    expect(autoCollapses(703, 280)).toBe(true);
    expect(autoCollapses(704, 280)).toBe(false);
    expect(autoCollapses(0, 280)).toBe(false); // not measured yet
    expect(layout(defaultPrefs, 600)).toEqual({ mode: "rail", width: 88, auto: true });
    expect(layout(defaultPrefs, 1040)).toEqual({ mode: "expanded", width: 280, auto: false });
    expect(layout({ expandedWidth: 400, isCollapsed: false }, 820)).toMatchObject({ mode: "rail", auto: true });
    expect(layout({ expandedWidth: 300, isCollapsed: true }, 1600)).toEqual({ mode: "rail", width: 88, auto: false });
  });

  it("steps by 8 with the arrow keys, collapses past the minimum, Home/End/Enter", () => {
    const p = { expandedWidth: 280, isCollapsed: false };
    expect(keyAdjust(p, "ArrowRight")).toEqual({ expandedWidth: 288, isCollapsed: false });
    expect(keyAdjust(p, "ArrowLeft")).toEqual({ expandedWidth: 272, isCollapsed: false });
    expect(keyAdjust({ expandedWidth: 240, isCollapsed: false }, "ArrowLeft")).toEqual({ expandedWidth: 240, isCollapsed: true });
    expect(keyAdjust({ expandedWidth: 240, isCollapsed: true }, "ArrowRight")).toEqual({ expandedWidth: 240, isCollapsed: false });
    expect(keyAdjust({ expandedWidth: 396, isCollapsed: false }, "ArrowRight")?.expandedWidth).toBe(400);
    expect(keyAdjust(p, "Home")).toEqual({ expandedWidth: 240, isCollapsed: false });
    expect(keyAdjust(p, "End")).toEqual({ expandedWidth: 400, isCollapsed: false });
    expect(keyAdjust(p, "Enter")).toEqual(toggle(p));
    expect(keyAdjust(p, "a")).toBeNull();
  });

  it("round-trips the remembered {expandedWidth, isCollapsed} and survives junk", () => {
    expect(parsePrefs(serializePrefs({ expandedWidth: 333, isCollapsed: true }))).toEqual({ expandedWidth: 333, isCollapsed: true });
    expect(parsePrefs(null)).toEqual(defaultPrefs);
    expect(parsePrefs("{oops")).toEqual(defaultPrefs);
    expect(parsePrefs("null")).toEqual(defaultPrefs);
    expect(parsePrefs(JSON.stringify({ expandedWidth: 9999, isCollapsed: "yes" }))).toEqual({ expandedWidth: 400, isCollapsed: false });
    expect(SIDEBAR.storageKey).toBe("jaeger.sidebar.v1");
  });
});
