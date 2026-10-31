import { describe, expect, it } from "vitest";
import { sizeClass } from "../shell/breakpoints";
import { ariaLabel, avatarStateFor, buildExtension, clampOrbit, clampZoom, loadMode, nextMode, saveMode, assetUrl, type AssetRecord } from "./avatarModel";

const mem = () => { const m = new Map<string, string>(); return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) }; };

describe("avatar model", () => {
  it("maps presence to avatar states (§2)", () => {
    expect(avatarStateFor("working")).toBe("thinking");
    expect(avatarStateFor("waiting_approval")).toBe("blocked");
    expect(avatarStateFor("stopped")).toBe("offline");
    expect(avatarStateFor(undefined)).toBe("idle");
    expect(avatarStateFor("working", { speaking: true })).toBe("speaking");
    expect(avatarStateFor("idle", { listening: true })).toBe("listening");
  });
  it("persists panel mode per agent and cycles", () => {
    const s = mem();
    expect(loadMode("a", "expanded", false, s)).toBe("expanded");
    expect(loadMode("a", "regular", false, s)).toBe("rail");
    expect(loadMode("a", "medium", false, s)).toBe("mini");
    expect(loadMode("a", "wide", true, s)).toBe("hidden");
    saveMode("a", "rail", "expanded", s); saveMode("b", "hidden", "compact", s);
    expect(loadMode("a", "expanded", false, s)).toBe("rail"); expect(loadMode("a", "compact", false, s)).toBe("mini"); expect(loadMode("b", "compact", false, s)).toBe("hidden");
    expect(nextMode("expanded")).toBe("rail"); expect(nextMode("rail")).toBe("hidden"); expect(nextMode("hidden")).toBe("expanded");
  });
  it("size classes (RESPONSIVE §1)", () => {
    expect([380, 600, 672, 840, 1199, 1440, 1920].map(sizeClass)).toEqual(["compact", "medium", "medium", "regular", "regular", "expanded", "wide"]);
  });
  it("clamps orbit and zoom (§3)", () => {
    expect(clampOrbit(90, -40)).toEqual({ yaw: 60, pitch: -10 });
    expect(clampZoom(9)).toBe(2.5); expect(clampZoom(0.1)).toBe(0.6);
  });
  it("labels and urls", () => {
    expect(ariaLabel("Jaeger", "speaking", "warm")).toBe("Jaeger avatar, speaking, warm");
    expect(assetUrl("jaeger-asset://" + "a".repeat(64))).toBe(`/v1/assets/${"a".repeat(64)}/file`);
    expect(assetUrl("file:///x")).toBeUndefined();
  });
  it("builds an extension that only references expressions the file has", () => {
    const vrm = { uri: "jaeger-asset://x", sha256: "x", format: "vrm", expressions: ["happy", "aa"], name: "m" } as unknown as AssetRecord;
    const fb = { uri: "jaeger-asset://y", sha256: "y", format: "image" } as unknown as AssetRecord;
    const e = buildExtension(vrm, fb);
    expect(e.states.listening.expression).toBe("neutral");
    expect(Object.keys(e.emotions)).toEqual(["neutral", "happy"]);
    expect(e.visemes?.profile).toBe("vrm5");
    expect(buildExtension(fb, fb).format_version).toBeNull();
  });
});
