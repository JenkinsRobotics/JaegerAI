import { afterEach, describe, expect, it, vi } from "vitest";
import { applyPreset, choosePreset, isPreset, PRESET_KEY, PRESETS, storedPreset, syncPresetFromGateway } from "./layoutPresets";

afterEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

describe("layout presets", () => {
  it("ships the four presets with Glass as the default", () => {
    expect(PRESETS.map((p) => p.id)).toEqual(["glass", "arc", "linear", "dia"]);
    expect(storedPreset()).toBe("glass");
    expect(isPreset("arc")).toBe(true);
    expect(isPreset("dock")).toBe(false);
  });
  it("applies config to <html> and remembers it locally", () => {
    applyPreset("arc");
    const d = document.documentElement.dataset;
    expect([d.layout, d.nav, d.command, d.glass]).toEqual(["arc", "sidebar", "sidebar", "true"]);
    expect(localStorage.getItem(PRESET_KEY)).toBe("arc");
    applyPreset("linear");
    expect([d.layout, d.nav, d.command, d.glass]).toEqual(["linear", "topbar+sidebar", "field", "false"]);
  });
  it("saves to the Gateway and falls back to local when it is unreachable", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ preset: "dia" }), { status: 200 }));
    expect(await choosePreset("dia")).toBe(true);
    expect(f.mock.calls[0][0]).toBe("/v1/ui/layout");
    expect(JSON.parse(String((f.mock.calls[0][1] as RequestInit).body))).toEqual({ preset: "dia" });
    f.mockRejectedValue(new Error("offline"));
    expect(await choosePreset("glass")).toBe(false);
    expect(storedPreset()).toBe("glass");
  });
  it("adopts the shared Gateway choice and ignores junk", async () => {
    applyPreset("glass");
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({ preset: "linear" }), { status: 200 }));
    expect(await syncPresetFromGateway()).toBe("linear");
    expect(document.documentElement.dataset.layout).toBe("linear");
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({ preset: "nope" }), { status: 200 }));
    expect(await syncPresetFromGateway()).toBe("linear");
  });
});
