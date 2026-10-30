/**
 * Widget platform tests (Jenkins Robotics, 2026-10-29, original).
 *
 * The load-bearing assertion: a widget whose loader fails MUST render an error and
 * MUST NOT emit any number. That is the regression guard for the mock dashboard this
 * platform replaces.
 */
import { describe, expect, it } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { WidgetSlot } from "./host/WidgetSlot";
import { WidgetFrame, observedLabel } from "./primitives/WidgetFrame";
import { Sparkline } from "./primitives/Sparkline";
import { Skeleton } from "./primitives/Skeleton";
import { parseDoc, emptyDoc, addItem, removeItem, withHost } from "./layoutStore";
import { gatewayHealthWidget } from "./definitions/gatewayHealth";
import { customAiWidget, specKey, specToUnit, type AiWidgetSpec } from "./definitions/customAi";
import type { JaegerSource } from "../api/source";
import type { WidgetDef } from "./types";

/** Minimal source stub. Only the members a test needs; everything else is absent. */
const sourceWith = (overrides: Partial<JaegerSource>): JaegerSource =>
  ({ kind: "live", ...overrides }) as unknown as JaegerSource;

async function mount(node: React.ReactNode) {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () => {
    root.render(node);
  });
  return { host, root };
}

describe("widget error contract", () => {
  const failing: WidgetDef<void, never> = {
    kind: "test.failing",
    title: "Broken",
    about: "Never loads",
    sizes: ["md"],
    hosts: ["page"],
    skeleton: <Skeleton lines={2} />,
    load: () => Promise.reject(new Error("gateway said no")),
    view: () => <span>should never render</span>,
  };

  it("renders an error and no data when load() rejects", async () => {
    const { host } = await mount(
      <WidgetSlot def={failing as never} source={sourceWith({})} size="md" tint="full" host="page" />,
    );
    await act(async () => { await Promise.resolve(); });
    expect(host.textContent).toContain("gateway said no");
    expect(host.textContent).not.toContain("should never render");
  });

  it("reports a missing source instead of showing zeros", async () => {
    const { host } = await mount(
      <WidgetSlot def={failing as never} source={undefined} size="md" tint="full" host="page" />,
    );
    await act(async () => { await Promise.resolve(); });
    expect(host.textContent).toContain("No Jaeger source");
  });

  it("shows a skeleton, never data, before load resolves", async () => {
    const pending: WidgetDef<void, never> = {
      ...failing,
      kind: "test.pending",
      load: () => new Promise<never>(() => {}),
    };
    const { host } = await mount(
      <WidgetSlot
        def={pending as never}
        source={sourceWith({})}
        size="md"
        tint="full"
        host="page"
      />,
    );
    expect(host.querySelector(".wg-skeleton")).not.toBeNull();
  });
});

describe("gateway health widget", () => {
  it("maps real diagnostics fields without inventing values", async () => {
    const data = await gatewayHealthWidget.load(
      sourceWith({
        diagnostics: () =>
          Promise.resolve({
            sessions: 7,
            requests: { ok: 40, failed: 2 },
            approvals: { pending: 3 },
            handoffs: {},
            unknown_requests: [],
            unknown_list_limit: 20,
            process_id: 4242,
            server_module_sha256: "deadbeef",
            fingerprint_scope: "test",
            observed_at: 1,
            read_only: true,
          }),
      }),
      // Void params: the definition takes none.
      undefined as never,
    );
    expect(data.diagnostics.sessions).toBe(7);
    expect(data.pendingApprovals).toBe(3);
    expect(data.requestTotals).toEqual([
      { key: "ok", count: 40 },
      { key: "failed", count: 2 },
    ]);
  });

  it("throws when the gateway has no diagnostics route", async () => {
    await expect(gatewayHealthWidget.load(sourceWith({}), undefined as never)).rejects.toThrow(
      /does not expose diagnostics/,
    );
  });

  it("does not render numbers while loading", async () => {
    const { host } = await mount(
      <WidgetSlot
        def={gatewayHealthWidget as never}
        source={sourceWith({ diagnostics: () => new Promise(() => {}) })}
        size="md"
        tint="full"
        host="page"
      />,
    );
    expect(host.querySelector(".wg-skeleton")).not.toBeNull();
    expect(host.textContent).not.toMatch(/\d+\s*sessions/);
  });
});

describe("custom AI widget", () => {
  const spec: AiWidgetSpec = {
    v: 1,
    source: "diagnostics",
    title: "Pending approvals",
    about: "Shows pending approvals",
    metrics: [
      { key: "approvals.pending", label: "Pending" },
      { key: "requests.failed", label: "Failed" },
    ],
    chart: "bar",
    size: "md",
    hosts: ["page"],
  };

  it("loads only the metric keys from the real diagnostics snapshot", async () => {
    const data = await customAiWidget.load(
      sourceWith({
        diagnostics: () =>
          Promise.resolve({
            sessions: 7,
            requests: { completed: 40, failed: 2 },
            approvals: { pending: 3 },
            handoffs: {},
            unknown_requests: [],
            unknown_list_limit: 20,
            process_id: 4242,
            server_module_sha256: "x",
            fingerprint_scope: "test",
            observed_at: 1700000000,
            read_only: true,
          }),
      }),
      { spec },
    );
    expect(data.metrics).toEqual([
      { label: "Pending", value: 3 },
      { label: "Failed", value: 2 },
    ]);
  });

  it("reports null for metric keys the gateway does not report (never invents)", async () => {
    const data = await customAiWidget.load(
      sourceWith({
        diagnostics: () =>
          Promise.resolve({
            sessions: 1,
            requests: {},
            approvals: {},
            handoffs: {},
            unknown_requests: [],
            unknown_list_limit: 0,
            process_id: 1,
            server_module_sha256: "x",
            fingerprint_scope: "test",
            observed_at: 1,
            read_only: true,
          }),
      }),
      { spec: { ...spec, metrics: [{ key: "requests.cancelled", label: "Cancelled" }] } },
    );
    expect(data.metrics).toEqual([{ label: "Cancelled", value: null }]);
  });

  it("rejects when no spec was persisted with the widget", async () => {
    await expect(customAiWidget.load(sourceWith({}), {} as never)).rejects.toThrow(/No widget spec/);
  });

  it("rejects sources this build cannot read honestly", async () => {
    await expect(
      customAiWidget.load(sourceWith({}), { spec: { ...spec, source: "sessions" } }),
    ).rejects.toThrow(/diagnostics/);
  });

  it("specKey is stable per spec and specToUnit maps sizes", () => {
    expect(specKey(spec)).toBe("custom.ai:diagnostics:approvals.pending+requests.failed");
    expect(specToUnit({ ...spec, size: "sm" })).toEqual({ w: 3, h: 3 });
    expect(specToUnit({ ...spec, size: "lg" })).toEqual({ w: 6, h: 6 });
    expect(specToUnit(spec)).toEqual({ w: 4, h: 4 });
  });
});

describe("primitives", () => {
  it("sparkline needs a label and handles a single point", async () => {
    const { host } = await mount(<Sparkline points={[5]} label="one sample" />);
    expect(host.querySelector("svg")).toBeNull();
    expect(host.querySelector("[role='img']")).not.toBeNull();
  });

  it("frame shows an observed-at stamp only when ready", async () => {
    const { host } = await mount(
      <WidgetFrame title="T" size="md" tint="full" status="loading">
        <span>body</span>
      </WidgetFrame>,
    );
    expect(host.querySelector(".wg-frame__foot")).toBeNull();
    expect(observedLabel(Date.now() - 30_000)).toBe("30s ago");
  });
});

describe("layout store", () => {
  it("drops unknown shapes instead of guessing", () => {
    expect(parseDoc({ v: 2, hosts: {} })).toEqual(emptyDoc());
    expect(parseDoc({ v: 1, hosts: { page: [{ i: "a" }, { nope: 1 }] } }).hosts.page).toEqual([
      { i: "a", x: 0, y: 0, w: 3, h: 2 },
    ]);
  });

  it("appends below existing items and removes by kind", () => {
    const start = withHost(emptyDoc(), "page", [{ i: "one", x: 0, y: 0, w: 3, h: 4 }]);
    const added = addItem(start, "page", { i: "two", x: 0, w: 3, h: 2 });
    expect(added.hosts.page[1]).toEqual({ i: "two", x: 0, y: 4, w: 3, h: 2 });
    expect(removeItem(added, "page", "one").hosts.page).toHaveLength(1);
  });

  it("preserves params on layout items and drops non-object params", () => {
    const spec = { v: 1, source: "diagnostics", title: "T", metrics: [], chart: "stat" };
    const parsed = parseDoc({
      v: 1,
      hosts: {
        page: [
          { i: "custom.ai:x", x: 0, y: 0, w: 3, h: 3, params: { spec } },
          { i: "bad", x: 0, y: 0, w: 3, h: 3, params: ["not", "an", "object"] },
        ],
      },
    });
    expect(parsed.hosts.page[0].params).toEqual({ spec });
    expect(parsed.hosts.page[1].params).toBeUndefined();
  });

  it("addItem carries params through", () => {
    const doc = addItem(emptyDoc(), "page", {
      i: "custom.ai:y",
      x: 0,
      w: 4,
      h: 4,
      params: { spec: { v: 1 } },
    });
    expect(doc.hosts.page[0].params).toEqual({ spec: { v: 1 } });
  });
});
