// 417d8a0c (the landed sessions contract): integer ids + next_before, float created_at, approval parts
// matched on tool+target, tool `state`, and one Idempotency-Key per uploaded file.
import { describe, expect, it, vi } from "vitest";
import { fromWirePage, type WirePage } from "./homeSession";
import { messagesToTurns } from "./webHost";
import { GatewayClient } from "../api/gateway";
import type { SessionMessage } from "../api/types";

describe("417d8a0c contract", () => {
  it("pages with integer ids and float epoch-second created_at", () => {
    const page = {
      messages: [
        { id: 12, session_id: "agent-jaeger", role: "assistant", kind: "message", sender_agent_id: "jaeger", created_at: 1760815200.25, content: "hi", parts: [], links: {} },
        { id: 11, session_id: "agent-jaeger", role: "user", kind: "message", sender_agent_id: null, created_at: 1760815199.5, content: "hello", parts: [], links: {} },
        { id: 10, session_id: "agent-jaeger", role: "system", kind: "summary", sender_agent_id: null, created_at: 1760815100.0, content: "Earlier…",
          parts: [], links: {}, summary: { covers_from: 1760810000.0, covers_to: 1760815000.0, message_count: 13 } },
      ],
      next_before: 10,
    } as unknown as WirePage;
    const ui = fromWirePage("agent-jaeger", page, (id) => id);
    expect(ui.before).toBe("10");
    expect(ui.turns.map((t) => t.turnId)).toEqual(["entry:10", "11"]);
    expect(ui.turns[1].createdAt).toBe(1760815199500);
    const summary = ui.entries["entry:10"];
    expect(summary).toMatchObject({ kind: "summary", id: "10", count: 13, toAt: 1760815000000 });
  });

  it("maps tool state and pending approvals (tool+target, call_id null)", () => {
    const messages = [
      { role: "user", content: "commit it", request_id: "r1" },
      { role: "assistant", content: "", parts: [
        { type: "tool", call_id: "c1", tool: "read_file", status: "done", state: "done", input: { path: "README.md" } },
        { type: "tool", call_id: "c2", tool: "shell", status: "running", state: "running", input: { command: "git commit -m x" } },
        { type: "approval", approval_id: "ap1", call_id: null, tool: "shell", target: "git commit -m x", status: "pending", state: "pending", decision: null },
        { type: "approval", approval_id: "ap0", call_id: null, tool: "write_file", target: "a.txt", status: "approved", state: "approved", decision: "once" },
      ] },
    ] as unknown as SessionMessage[];
    const [turn] = messagesToTurns(messages);
    expect(turn.parts.map((p) => p.kind)).toEqual(["toolInvocation", "toolInvocation", "confirmation"]);
    expect(turn.parts[0]).toMatchObject({ state: "completed" });
    expect(turn.parts[1]).toMatchObject({ toolName: "shell", state: "waitingForConfirmation" });
    expect(turn.parts[2]).toMatchObject({ callId: "ap1", title: "Run shell?", message: "git commit -m x" });
  });

  it("sends an Idempotency-Key with an upload", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ attachment_id: "att_1", name: "a.txt", mime: "text/plain", size: 1, sha256: "x" }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    try {
      await new GatewayClient("").uploadAttachment("agent-jaeger", { name: "a.txt", mime: "text/plain", data_base64: "YQ==" }, "key-1");
      const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
      expect((init.headers as Record<string, string>)["Idempotency-Key"]).toBe("key-1");
    } finally { vi.unstubAllGlobals(); }
  });
});
