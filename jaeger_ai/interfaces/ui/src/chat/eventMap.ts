import "../../../ide/media/timeline.js";
import { modelContext } from "./modelContext";
import { requestOutcome } from "./requestOutcome";
/* Gateway SSE event -> ChatPart mapping. ONE place, on purpose: this file is
 * meant to be regenerated from the gateway's events.schema.json later.
 * Event names follow core/gateway/event_bus.py EVENT_TYPES. */
import type { GatewayEvent } from "../api/types";
import type { ChatPart, TurnState, ToolInvocationState } from "./host";

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
    case "turn.steer": return {parts:[{kind:"userGuidance",text:str(p.text),steeringId:str(p.steering_id ?? event.event_id)}]};
    case "turn.model": return {parts:[{kind:"modelIdentity",actualModel:p.scope==="provider_reported"&&typeof p.actual_model==="string"?p.actual_model:null,scope:p.scope==="provider_reported"?"provider_reported":"unknown"}]};
    case "turn.context": return {parts: [{kind: "modelContext", outline: modelContext(p.outline)}]};
    case "agent.knowledge": {
      const documents = Array.isArray(p.documents) ? p.documents.filter((doc): doc is { id: string; revision: number; digest: string; title: string } => Boolean(doc && typeof doc === "object" && typeof doc.id === "string" && typeof doc.revision === "number" && typeof doc.digest === "string" && typeof doc.title === "string")) : [];
      return { parts: [{ kind: "knowledgeContext", documents }] };
    }
    case "turn.delta":
      return { parts: [{ kind: "markdownContent", text: str(p.delta ?? p.text),
        ...((p.content_type || p.channel) ? {role: ["commentary","final"].includes(str(p.content_type ?? p.channel)) ? str(p.content_type ?? p.channel) as "commentary"|"final" : "provisional" as const} : {}),
        ...(p.item_id ? {itemId:str(p.item_id)} : {}) }] };
    case "turn.reasoning":
      return { parts: [{ kind: "thinking", text: str(p.text ?? p.delta), durationMs: typeof p.duration_ms === "number" ? p.duration_ms : undefined }] };
    case "turn.reasoning.done":
      return { parts: [{ kind: "thinking", text: "", durationMs: typeof p.duration_ms === "number" ? p.duration_ms : undefined }] };
    case "turn.plan": {
      const plan=globalThis.JaegerTimeline.parsePlan(p);
      return plan.length ? {parts:[{kind:"plan",plan,explanation:str(p.explanation)}]} : null;
    }
    case "turn.checkpoint": return {parts:[{kind:"checkpoint",text:str(p.text ?? p.message)}]};
    case "sources": {
      const sources=globalThis.JaegerTimeline.parseSources(p);
      return sources.length ? {parts:[{kind:"sources",sources}]} : null;
    }
    case "search.count": {
      const count=globalThis.JaegerTimeline.parseSearchCount(p);
      return count ? {parts:[{kind:"searchCount",...count}]} : null;
    }
    case "follow_ups": {
      const prompts=globalThis.JaegerTimeline.parseFollowUps(p);
      return prompts.length ? {parts:[{kind:"followUps",prompts}]} : null;
    }
    case "turn.progress":
      return { parts: [{ kind: "progress", message: str(p.message ?? p.text ?? p.summary) }] };
    case "tool.started":
      return { parts: [{ kind: "toolInvocation", callId: str(p.call_id ?? p.activity_id), toolName: str(p.tool), input: p.input ?? p.args ?? null, state: "executing" }] };
    case "tool.done":
    case "tool.completed":
      return { parts: [{ kind: "toolInvocation", callId: str(p.call_id ?? p.activity_id), toolName: str(p.tool), input: p.input ?? p.args ?? null, state: "completed", output: p.output ?? p.result, summary: str(p.summary ?? p.text) || undefined }] };
    case "tool.error":
    case "tool.failed":
      return {
        parts: [
          { kind: "toolInvocation", callId: str(p.call_id ?? p.activity_id), toolName: str(p.tool), input: p.input ?? p.args ?? null, state: (["denied", "rejected", "unsupported", "unknown", "cancelled"].includes(str(p.outcome)) ? str(p.outcome) : "failed") as ToolInvocationState, output: p.error, summary: str(p.summary ?? p.text) || undefined },
          { kind: "error", message: str(p.error ?? p.message ?? "Tool failed") },
        ],
      };
    case "approval.request": {
      const parts: ChatPart[] = [];
      if (p.call_id) parts.push({ kind: "toolInvocation", callId: str(p.call_id), toolName: str(p.tool), input: p.input ?? p.args ?? null, state: "waitingForConfirmation" });
      parts.push({ kind: "confirmation", callId: str(p.approval_id ?? p.id ?? p.call_id), title: str(p.title ?? (p.tool ? `Run ${str(p.tool)}?` : "Approval needed")), message: str(p.prompt ?? p.summary ?? p.message) });
      return { parts };
    }
    case "approval.resolved": {
      const id=str(p.approval_id ?? p.id);
      const decision=typeof p.approved==='boolean' ? (p.approved?'approve':'deny') :
        ['deny','cancelled','expired'].includes(str(p.decision)) ? 'deny' : ['once','session','always','allow','yes'].includes(str(p.decision)) ? 'approve' : undefined;
      return id && decision ? {parts:[{kind:'confirmation',callId:id,title:'',message:'',decision}]} : null;
    }
    case "clarify.request": {
      const choices = Array.isArray(p.choices) ? p.choices.map(str).filter(Boolean) : [];
      return { parts: [{ kind: "question", callId: str(p.clarify_id), title: str(p.question), sessionId: str(p.session_id) || undefined,
        revision: typeof p.revision === "number" ? p.revision : 1, status: "pending", options: choices.map((label, i) => ({ id: `c${i}`, label })) }] };
    }
    case "clarify.resolved": {
      const status = p.status === "answered" || p.status === "cancelled" || p.status === "expired" ? p.status : undefined;
      return status ? { parts: [{ kind: "question", callId: str(p.clarify_id), title: "", options: [], status } as ChatPart] } : null;
    }
    case "agent.handoff":
    case "agent.handoff.finished": {
      const h = (p.handoff && typeof p.handoff === "object" ? p.handoff : p) as Payload;
      const direction = event.event === "agent.handoff" ? "to" : "from";
      const agentId = str(direction === "to" ? h.to_agent_id : h.to_agent_id ?? h.from_agent_id);
      return { parts: [{ kind: "handoff", status: (h.metadata as Payload | undefined)?.delivery_message_id ? "delivered" : str(h.status || "unverified"), handoffId: str(h.id ?? h.handoff_id), agentId, agentName: agentName(agentId), count: 1, direction }] };
    }
    case "turn.reconciled": {
      // Reconciliation is an observation, not a success event. Share the
      // durable lookup's terminal semantics; incomplete/malformed receipts
      // must never turn unknown execution into a successful completion.
      const status = ["completed", "failed", "cancelled", "execution_unknown"].includes(str(p.status))
        ? str(p.status) : "execution_unknown";
      const parts: ChatPart[] = [];
      const state = requestOutcome({ status, result: {
        ...(typeof p.output === "string" ? { output: p.output } : {}),
        ...(typeof p.error === "string" ? { error: p.error } : {}),
        ...(typeof p.summary === "string" ? { summary: p.summary } : {}),
      } }, part => parts.push(part));
      return { parts, state };
    }
    case "turn.finish": {
      const output = str(p.output);
      return { parts: output ? [{kind:"markdownContent",text:output,role:"final",itemId:"final"}] : [], state: "complete" };
    }
    case "turn.unknown":
      return { parts: [{ kind: "error", message: str(p.error ?? p.message ?? "The gateway lost track of this turn. It will not be resent.") }], state: "unknown" };
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
