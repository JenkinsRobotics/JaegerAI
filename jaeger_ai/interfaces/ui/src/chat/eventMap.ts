/* Gateway SSE event -> ChatPart mapping. ONE place, on purpose: this file is
 * meant to be regenerated from the gateway's events.schema.json later.
 * Event names follow core/gateway/event_bus.py EVENT_TYPES. */
import type { GatewayEvent } from "../api/types";
import type { ChatPart, TurnState } from "./host";

export interface MappedEvent {
  parts: ChatPart[];
  /** Set when the event ends the turn. */
  state?: TurnState;
}

type Payload = Record<string, unknown>;
const str = (value: unknown): string => (typeof value === "string" ? value : value == null ? "" : String(value));

export function mapEvent(event: GatewayEvent, agentName: (id: string) => string = (id) => id): MappedEvent | null {
  const p: Payload = (event.payload && typeof event.payload === "object" ? event.payload : event) as Payload;
  switch (event.event) {
    case "turn.delta":
      return { parts: [{ kind: "markdownContent", text: str(p.delta ?? p.text) }] };
    case "turn.reasoning":
      return { parts: [{ kind: "thinking", text: str(p.text ?? p.delta), durationMs: typeof p.duration_ms === "number" ? p.duration_ms : undefined }] };
    case "turn.reasoning.done":
      return { parts: [{ kind: "thinking", text: "", durationMs: typeof p.duration_ms === "number" ? p.duration_ms : undefined }] };
    case "turn.progress":
    case "turn.plan":
      return { parts: [{ kind: "progress", message: str(p.message ?? p.text ?? p.summary) }] };
    case "tool.started":
      return { parts: [{ kind: "toolInvocation", callId: str(p.call_id ?? p.activity_id), toolName: str(p.tool), input: p.input ?? p.args ?? null, state: "executing" }] };
    case "tool.done":
      return { parts: [{ kind: "toolInvocation", callId: str(p.call_id ?? p.activity_id), toolName: str(p.tool), input: p.input ?? p.args ?? null, state: "completed", output: p.output ?? p.result }] };
    case "tool.error":
      return {
        parts: [
          { kind: "toolInvocation", callId: str(p.call_id ?? p.activity_id), toolName: str(p.tool), input: p.input ?? p.args ?? null, state: "cancelled", output: p.error },
          { kind: "error", message: str(p.error ?? p.message ?? "Tool failed") },
        ],
      };
    case "approval.request": {
      const parts: ChatPart[] = [];
      if (p.call_id) parts.push({ kind: "toolInvocation", callId: str(p.call_id), toolName: str(p.tool), input: p.input ?? p.args ?? null, state: "waitingForConfirmation" });
      parts.push({ kind: "confirmation", callId: str(p.approval_id ?? p.id ?? p.call_id), title: str(p.title ?? (p.tool ? `Run ${str(p.tool)}?` : "Approval needed")), message: str(p.prompt ?? p.summary ?? p.message) });
      return { parts };
    }
    case "agent.handoff":
    case "agent.handoff.finished": {
      const h = (p.handoff && typeof p.handoff === "object" ? p.handoff : p) as Payload;
      const direction = event.event === "agent.handoff" ? "to" : "from";
      const agentId = str(direction === "to" ? h.to_agent_id : h.to_agent_id ?? h.from_agent_id);
      return { parts: [{ kind: "handoff", handoffId: str(h.id ?? h.handoff_id), agentId, agentName: agentName(agentId), count: 1, direction }] };
    }
    case "turn.finish":
    case "turn.reconciled":
      return { parts: [], state: "complete" };
    case "turn.unknown":
      return { parts: [{ kind: "error", message: str(p.error ?? p.message ?? "The gateway lost track of this turn.") }], state: "failed" };
    case "turn.cancelled":
      return { parts: [], state: "cancelled" };
    case "turn.failed":
      return { parts: [{ kind: "error", message: str(p.error ?? p.message ?? "Turn failed") }], state: "failed" };
    case "notification.proactive":
      return { parts: [{ kind: "warning", message: str(p.message ?? p.text) }] };
    default:
      return null;
  }
}
