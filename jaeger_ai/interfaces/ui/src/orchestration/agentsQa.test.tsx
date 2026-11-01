import { describe, expect, it, vi, beforeEach } from "vitest";
import { FEED_KINDS, gatewayActivity, resetActivityProbe } from "./adapter";

const names = (id: string) => id;
const page = (items: unknown[] = []) => new Response(JSON.stringify({ items, has_more: false, next_before: null }), { status: 200 });

describe("agents tab QA r1", () => {
  beforeEach(() => resetActivityProbe());
  it("asks the gateway only for kinds the feed renders", async () => {
    const f = vi.fn(async () => page());
    await gatewayActivity("http://g", f as unknown as typeof fetch)({ names });
    const url = new URL(String((f.mock.calls[0] as unknown[])[0]));
    expect(url.searchParams.get("kind")?.split(",")).toEqual(FEED_KINDS);
    expect(url.searchParams.get("limit")).toBe("50");
  });
  it("every requested kind is one feed.ts renders", () => {
    expect(FEED_KINDS).toContain("handoff.sent");
    expect(FEED_KINDS).not.toContain("backlog.updated");
  });
  it("no agents/empty history gives no rows", async () => {
    const r = await gatewayActivity("http://e", (async () => page()) as unknown as typeof fetch)({ names });
    expect(r.rows).toEqual([]);
  });
  it("404 is remembered, 500 throws", async () => {
    const f404 = vi.fn(async () => new Response("", { status: 404 }));
    const a = gatewayActivity("http://n", f404 as unknown as typeof fetch);
    expect((await a({ names })).rows).toEqual([]);
    await a({ names });
    expect(f404).toHaveBeenCalledTimes(1);
    const a500 = gatewayActivity("http://f", (async () => new Response("", { status: 500 })) as unknown as typeof fetch);
    await expect(a500({ names })).rejects.toThrow("activity 500");
  });
});
