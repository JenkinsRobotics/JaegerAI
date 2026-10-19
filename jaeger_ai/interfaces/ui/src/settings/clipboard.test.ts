import { afterEach, expect, it, vi } from "vitest";
import { WebHost } from "../chat/webHost";
import type { JaegerSource } from "../api/source";
afterEach(() => vi.unstubAllGlobals());
it("clipboard failure is an error, never a successful Copy ID acknowledgement", async () => {
  const host = new WebHost({} as JaegerSource);
  vi.stubGlobal("navigator", {});
  await expect(host.copy("agent:worker")).rejects.toThrow("Clipboard unavailable");
  const writeText = vi.fn().mockRejectedValue(new Error("denied"));
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  await expect(host.copy("agent:worker")).rejects.toThrow("denied");
  expect(writeText).toHaveBeenCalledWith("agent:worker");
});
