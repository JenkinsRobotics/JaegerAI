import { describe, expect, it } from "vitest";
import { LAYOUT_KEY, loadLayout, saveLayout } from "./WindowManager";

const mem = () => { const m = new Map<string, string>(); return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) }; };

describe("window layout persistence", () => {
  it("defaults to Chat open with every page in the dock", () => {
    const l = loadLayout(mem());
    expect(l.open).toEqual(["chat"]);
    expect(l.order).toContain("work");
    expect(l.order).toHaveLength(10);
  });
  it("round-trips through storage and drops unknown pages", () => {
    const s = mem();
    saveLayout({ open: ["home", "chat", "work"], minimized: ["work"], order: ["chat", "home", "work"] }, s);
    s.setItem(LAYOUT_KEY, JSON.stringify({ ...JSON.parse(s.getItem(LAYOUT_KEY)!), open: ["work", "bogus"] }));
    const l = loadLayout(s);
    expect(l.open).toEqual(["chat", "work"]);
    expect(l.minimized).toEqual(["work"]);
    expect(l.order).toEqual(["chat", "agents", "work", "research", "studio", "machine", "library", "automations", "feed", "settings"]);
    expect(l.order).toContain("settings");
  });
  it("migrates saved layouts from the 17-tab dock", () => {
    const s = mem();
    s.setItem(LAYOUT_KEY, JSON.stringify({ open: ["home", "chat", "tasks", "calendar", "compare"], minimized: ["calendar"], order: ["chat", "home", "characters", "tasks", "documents"] }));
    const l = loadLayout(s);
    expect(l.open).toEqual(["chat", "work", "settings"]);
    expect(l.minimized).toEqual(["work"]);
    expect(l.order.slice(0, 4)).toEqual(["chat", "agents", "work", "research"]);
    expect(new Set(l.order).size).toBe(l.order.length);
  });
  it("survives corrupt storage", () => {
    const s = mem(); s.setItem(LAYOUT_KEY, "{not json");
    expect(loadLayout(s).open).toEqual(["chat"]);
  });
});
