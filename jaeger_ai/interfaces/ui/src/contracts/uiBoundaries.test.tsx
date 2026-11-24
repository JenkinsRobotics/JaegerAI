import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CapabilityGate, evaluateCapabilities } from "../core";
import { MockSource } from "../api/mock";
import { availableFeaturesFor, getFeatureModule, UI_FEATURE_MODULES } from "../features";
import { describeHostCapabilities, type ChatHost } from "../hosts";
import type { JaegerSource } from "../contracts";

describe("UI modular boundaries (ui-contracts / ui-core / ui-features / ui-hosts)", () => {
  it("declares Gateway capabilities for all 8 core UI feature modules", () => {
    expect(UI_FEATURE_MODULES.map((m) => m.id)).toEqual([
      "chat",
      "tasks",
      "tools",
      "browser",
      "memory",
      "skills",
      "settings",
      "diagnostics",
    ]);
    for (const mod of UI_FEATURE_MODULES) {
      expect(mod.authoritativeOwner).toBe("gateway");
      expect(mod.requiredCapabilities.length).toBeGreaterThan(0);
    }
    expect(getFeatureModule("chat").requiredCapabilities).toContain("chat.sessions");
  });

  it("CapabilityGate renders children when supported and honest unavailable UI when missing", () => {
    const full = new MockSource();
    const { rerender } = render(
      <CapabilityGate source={full} requires={["chat.sessions", "chat.approvals"]} featureName="Chat">
        <div data-testid="chat-body">Live Chat</div>
      </CapabilityGate>,
    );
    expect(screen.getByTestId("chat-body")).toBeTruthy();

    const minimal = { kind: "live" } as unknown as JaegerSource;
    rerender(
      <CapabilityGate source={minimal} requires={["diagnostics.gateway"]} featureName="Diagnostics">
        <div data-testid="diag-body">Live Diagnostics</div>
      </CapabilityGate>,
    );
    expect(screen.queryByTestId("diag-body")).toBeNull();
    const fallback = screen.getByTestId("capability-unavailable");
    expect(fallback.getAttribute("data-missing")).toBe("diagnostics.gateway");
    expect(fallback.textContent).toContain("Diagnostics unavailable");
  });

  it("evaluates available vs unavailable features honestly for a partial Gateway source", () => {
    const partial = {
      kind: "live",
      sessions: async () => [],
      send: async () => ({ request_id: "r1" }),
      stream: async () => {},
      approve: async () => {},
      tasks: async () => [],
    } as unknown as JaegerSource;

    const { available, unavailable } = availableFeaturesFor(partial);
    expect(available.map((f) => f.id)).toEqual(["chat", "tasks"]);
    expect(unavailable.map((u) => u.feature.id)).toContain("diagnostics");
    expect(evaluateCapabilities(null, ["chat.sessions"]).supported).toBe(false);
  });

  it("describes host capabilities neutrally across WebUI, VS Code, and macOS native hosts", () => {
    const nativeHost = {
      kind: "native",
      capabilities: { voice: true },
      openFile: () => {},
      onThemeChanged: () => () => {},
    } as unknown as ChatHost;

    expect(describeHostCapabilities(nativeHost)).toEqual({
      kind: "native",
      voice: true,
      openFile: true,
      themeSync: true,
      nativeWindow: true,
    });
  });
});
