import { afterEach, expect, it, vi } from "vitest";
import { GatewayClient } from "./gateway";
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
function pendingFetch() {
  return vi.fn((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
    init.signal?.addEventListener("abort", () => reject(new DOMException("signal is aborted without reason", "AbortError")), { once: true });
  }));
}
it("reports a readable timeout without retrying a request", async () => {
  vi.useFakeTimers(); const fetch = pendingFetch(); vi.stubGlobal("fetch", fetch);
  const request = new GatewayClient("").json("/v1/sessions/s/control");
  const result = expect(request).rejects.toMatchObject({ status: 408, message: expect.stringContaining("Nothing was automatically resent") });
  await vi.advanceTimersByTimeAsync(15000); await result;
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("preserves caller cancellation instead of calling it a timeout", async () => {
  vi.stubGlobal("fetch", pendingFetch()); const controller = new AbortController();
  const request = new GatewayClient("").json("/v1/sessions/s/control", undefined, undefined, undefined, controller.signal);
  const result = expect(request).rejects.toMatchObject({ name: "AbortError" });
  controller.abort(); await result;
});
