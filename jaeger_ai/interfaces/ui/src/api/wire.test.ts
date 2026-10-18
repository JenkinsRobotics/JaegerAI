import { describe, expect, it } from "vitest";
import { followTurn } from "../chat/followTurn";
import type { ChatPart } from "../chat/host";
import { normalizeFrame } from "./gateway";
import { parseSSEChunk } from "./sse";
import type { GatewayEvent } from "./types";

// Shapes captured from the loopback test stack (gateway 127.0.0.1:43428, 2026-10-17).
const wire = [
  'id: 20\nevent: turn.finish\ndata: {"event_id": 20, "session_id": "s", "event": "turn.finish", "timestamp": 1, "data": {"output": "old", "status": "completed", "request_id": "rq-0", "turn_id": "t0"}}',
  'id: 264\nevent: turn.start\ndata: {"event_id": 264, "session_id": "s", "event": "turn.start", "timestamp": 2, "data": {"turn_id": "t1", "request_id": "rq-1", "message_id": 3, "text": "ping"}}',
  'id: 265\nevent: turn.reasoning\ndata: {"event_id": 265, "session_id": "s", "event": "turn.reasoning", "timestamp": 3, "data": {"turn_id": "t1", "request_id": "rq-1", "text": "Okay"}}',
  'id: 266\nevent: turn.reasoning.done\ndata: {"event_id": 266, "session_id": "s", "event": "turn.reasoning.done", "timestamp": 4, "data": {"turn_id": "t1", "request_id": "rq-1", "duration_ms": 4200}}',
  'id: 267\nevent: turn.delta\ndata: {"event_id": 267, "session_id": "s", "event": "turn.delta", "timestamp": 5, "data": {"turn_id": "t1", "request_id": "rq-1", "delta": "pong", "channel": "provisional"}}',
  'id: 268\nevent: turn.finish\ndata: {"event_id": 268, "session_id": "s", "event": "turn.finish", "timestamp": 6, "data": {"output": "pong", "status": "completed", "request_id": "rq-1", "turn_id": "t1"}}',
].join("\n\n") + "\n\n";

describe("gateway wire envelope", () => {
  const events: GatewayEvent[] = parseSSEChunk(wire).frames.map(normalizeFrame);
  it("lifts request_id/turn_id out of the inner data object", () => {
    expect(events[1]).toMatchObject({ event: "turn.start", event_id: 264, request_id: "rq-1", turn_id: "t1", payload: { text: "ping" } });
  });
  it("follows a real turn end to end and ignores the older turn's finish", async () => {
    const parts: ChatPart[] = [];
    const result = await followTurn({
      source: { stream: async (_s, _c, onEvent) => { events.forEach(onEvent); } },
      sessionId: "s", requestId: "rq-1", turnId: "t1", cursor: 263, signal: new AbortController().signal,
      onPart: (p) => parts.push(p), sleep: async () => {},
    });
    expect(result.state).toBe("complete");
    expect(parts.map((p) => p.kind)).toEqual(["thinking", "thinking", "markdownContent"]);
  });
});
