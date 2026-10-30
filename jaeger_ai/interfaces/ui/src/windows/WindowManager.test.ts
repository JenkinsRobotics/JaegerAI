import { describe, expect, it } from "vitest";
import { LAYOUT_KEY, loadLayout, saveLayout } from "./WindowManager";

const mem = () => { const m = new Map<string, string>(); return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) }; };

describe("window layout persistence", () => {
  it("defaults to Home and Chat open with every page in the dock", () => {
    const l = loadLayout(mem());
    expect(l.open).toEqual(["home", "chat"]);
    expect(l.order).toContain("characters");
  });
  it("round-trips through storage and drops unknown pages", () => {
    const s = mem();
    saveLayout({ open: ["home", "chat", "tasks"], minimized: ["tasks"], order: ["chat", "home", "tasks"] }, s);
    s.setItem(LAYOUT_KEY, JSON.stringify({ ...JSON.parse(s.getItem(LAYOUT_KEY)!), open: ["tasks", "bogus"] }));
    const l = loadLayout(s);
    expect(l.open).toEqual(["chat", "home", "tasks"]);
    expect(l.minimized).toEqual(["tasks"]);
    expect(l.order.slice(0, 3)).toEqual(["chat", "home", "tasks"]);
    expect(l.order).toContain("settings");
  });
  it("survives corrupt storage", () => {
    const s = mem(); s.setItem(LAYOUT_KEY, "{not json");
    expect(loadLayout(s).open).toEqual(["home", "chat"]);
  });
});
