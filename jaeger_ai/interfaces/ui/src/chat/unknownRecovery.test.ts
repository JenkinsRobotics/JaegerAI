import { beforeEach, describe, expect, it, vi } from "vitest";
import { WebHost } from "./webHost";
import type { JaegerSource } from "../api/source";

beforeEach(() => localStorage.clear());
const unknownRow = (acknowledged?: object) => ({ request_id: "r1", session_id: "s", status: "execution_unknown", input_text: "long tool",
  result: { status: "execution_unknown", ...(acknowledged ? { acknowledged } : {}) } });

describe("an unknown outcome never locks the conversation (2026-10-21)", () => {
  it("an owner-acknowledged unknown request is no longer a pending intent", async () => {
    const source = { kind: "live", sessionControl: async () => ({ latest_request: { request_id: "r1", status: "execution_unknown" } }),
      requestStatus: async () => unknownRow({ by: "owner:webui", replayed: false }) } as unknown as JaegerSource;
    expect(await new WebHost(source).findPendingIntent("s")).toBeUndefined();
  });
  it("acknowledging posts once, never resends, and frees the device journal so the next send is admitted", async () => {
    const send = vi.fn(async () => { throw new TypeError("stream killed mid-turn"); });
    const requestStatus = vi.fn(async () => unknownRow());
    const acknowledgeUnknown = vi.fn(async () => unknownRow({ by: "owner:webui", replayed: false }));
    const source = { kind: "live", send, requestStatus, acknowledgeUnknown, stream: async () => {} } as unknown as JaegerSource;
    const host = new WebHost(source, []);
    // Killed stream: the first send's outcome stays unknown and its journal blocks a blind second send.
    expect((await host.startTurn({ sessionId: "s", turnId: "r1", message: "long tool" }, () => {}).done).state).toBe("unknown");
    expect(host.pendingIntent("s")?.requestId).toBe("r1");
    await host.acknowledgeUnknown("s", "r1");
    expect(acknowledgeUnknown).toHaveBeenCalledWith("s", "r1");
    expect(host.pendingIntent("s")).toBeUndefined();
    send.mockResolvedValueOnce({ session_id: "s", turn_id: "t2", request_id: "r2", status: "running" } as never);
    requestStatus.mockResolvedValue({ request_id: "r2", session_id: "s", status: "completed", result: { output: "OK" } } as never);
    expect((await host.startTurn({ sessionId: "s", turnId: "r2", message: "hello again" }, () => {}).done).state).toBe("complete");
    expect(send).toHaveBeenCalledTimes(2);                      // r1 never resent; r2 is the only new send
    expect(send.mock.calls.map(c => (c as unknown[])[2] ?? (c as unknown[])[1])).not.toContain(undefined);
  });
  it("an unconfirmed acknowledgement keeps the journal (no silent clearing)", async () => {
    const source = { kind: "live", acknowledgeUnknown: async () => unknownRow() } as unknown as JaegerSource;
    const host = new WebHost(source);
    await expect(host.acknowledgeUnknown("s", "r1")).rejects.toThrow("not confirmed");
  });
});
