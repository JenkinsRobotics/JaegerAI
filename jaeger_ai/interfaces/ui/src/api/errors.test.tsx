import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { agentsSidebarSlots } from "../agents/AgentsSidebar";
import { loadRoster } from "../agents/agentsStore";
import { WebHost } from "../chat/webHost";
import { mockAllowed, mockRequested } from "./index";
import type { JaegerSource } from "./source";

const PROD = { DEV: false };
const DEV = { DEV: true };

describe("mock gating (review: mock code in production)", () => {
  it("ignores ?mock=1 in production builds", () => {
    expect(mockAllowed(PROD)).toBe(false);
    expect(mockRequested("?mock=1", PROD)).toBe(false);
  });
  it("allows mock in dev, or in builds made with VITE_JAEGER_MOCK=1", () => {
    expect(mockRequested("?mock=1", DEV)).toBe(true);
    expect(mockRequested("", DEV)).toBe(false);
    expect(mockRequested("", { DEV: false, VITE_JAEGER_MOCK: "1" })).toBe(true);
    expect(mockRequested("?mock=0", { DEV: false, VITE_JAEGER_MOCK: "1" })).toBe(false);
  });
});

const down = new Error("connect ECONNREFUSED 127.0.0.1:8790");
const failing = { agents: async () => { throw down; }, agentsSummary: async () => { throw down; } };

describe("no silent fallback to fake data", () => {
  it("roster load rejects instead of inventing a roster", async () => {
    await expect(loadRoster(failing)).rejects.toThrow("ECONNREFUSED");
  });
  it("sidebar shows an ErrorState with Retry and the error text, and no agents", () => {
    const slots = agentsSidebarSlots({
      state: { agents: [], summaries: [], seen: {}, loading: false, error: down.message },
      selection: { type: "agent", agentId: "native:jaeger" },
      onSelect: () => {}, onNewChat: () => {}, onSearch: () => {}, onConnectApps: () => {}, onRetry: () => {}, userInitials: "MJ",
    });
    const html = renderToStaticMarkup(<>{slots.primary}</>);
    expect(html).toContain("Couldn&#x27;t load agents");
    expect(html).toContain("ECONNREFUSED");
    expect(html).toContain(">Retry<");
    expect(html).not.toContain("jg-supervisor");
  });
  it("session load surfaces the error instead of an empty 'New chat'", async () => {
    const source = { kind: "live", session: async () => { throw down; } } as unknown as JaegerSource;
    await expect(new WebHost(source).sessions.load("s1")).rejects.toThrow("ECONNREFUSED");
  });
});
