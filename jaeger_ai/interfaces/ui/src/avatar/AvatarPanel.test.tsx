import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AvatarPanel } from "./AvatarPanel";
import { AvatarStage } from "./AvatarStage";
import type { Agent } from "../api/types";

const agent = { id: "jaeger", name: "Jaeger" } as Agent;
const rec = { agent_id: "jaeger", avatar: null, asset: null, fallback_asset: null, live: { emotion: "warm", intensity: 0.5, updated_at: 1, source: "api" } };

describe("AvatarPanel", () => {
  beforeEach(() => { localStorage.clear(); vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(rec), { status: 200 }))); });
  afterEach(() => vi.unstubAllGlobals());
  it("docks on expanded, labels state + emotion, previews a state, and collapses to a rail", async () => {
    render(<AvatarPanel agent={agent} presence="working" size={{ cls: "expanded", short: false }} />);
    expect(await screen.findByRole("img", { name: "Jaeger avatar, thinking, warm" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Speaking/ }));
    expect(screen.getByRole("img", { name: /speaking/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Collapse avatar/ }));
    expect(screen.getByRole("button", { name: /Expand Jaeger's avatar/ })).toBeTruthy();
    expect(JSON.parse(localStorage.getItem("jaeger.avatar.panel")!)["jaeger@expanded"]).toBe("rail");
  });
  it("uses the rail on regular, hidden when short, and ⌥⌘A toggles", async () => {
    const { rerender } = render(<AvatarPanel agent={agent} size={{ cls: "regular", short: false }} />);
    expect(screen.getByRole("button", { name: /Expand Jaeger's avatar/ })).toBeTruthy();
    rerender(<AvatarPanel agent={agent} size={{ cls: "regular", short: true }} />);
    expect(screen.getByRole("button", { name: /Show Jaeger's avatar/ })).toBeTruthy();
    await act(async () => { fireEvent.keyDown(window, { code: "KeyA", altKey: true, metaKey: true }); });
    expect(screen.getByRole("img", { name: /Jaeger avatar/ })).toBeTruthy();
  });
  it("animates the built-in Jaeger character unless Still is selected", async () => {
    const native = { id: "native:jaeger", name: "Jaeger" } as Agent;
    const { container } = render(<AvatarPanel agent={native} clipState="working" size={{ cls: "expanded", short: false }} />);
    expect(await screen.findByRole("img", { name: "Jaeger avatar" })).toBeTruthy();
    expect(container.querySelector('video[src$="/working.mp4"]')).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Still" }));
    expect(container.querySelector("video")).toBeNull();
  });
});

describe("AvatarStage", () => {
  it("shows the portrait (never blank) when there is no model", () => {
    render(<AvatarStage name="Atlas" record={null} state="offline" emotion="neutral" portrait={<span>portrait</span>} />);
    expect(screen.getByText("portrait")).toBeTruthy();
    expect(screen.getByRole("img", { name: "Atlas avatar, offline, neutral" })).toBeTruthy();
  });
});
