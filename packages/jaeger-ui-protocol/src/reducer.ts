/**
 * Versioned pure reducer mapping GatewayEventEnvelope frames into SessionStreamState.
 */

import {
  PROTOCOL_VERSION,
  type ApprovalPart,
  type ChatMessage,
  type GatewayEventEnvelope,
  type MessagePart,
  type SessionStreamState,
  type ToolCallPart,
} from "./types";

export function createInitialSessionState(sessionId: string): SessionStreamState {
  return {
    protocolVersion: PROTOCOL_VERSION,
    sessionId,
    status: "idle",
    lastSeq: 0,
    messages: [],
    pendingApprovals: [],
    lastError: null,
  };
}

function ensureStreamingAssistant(
  messages: ChatMessage[],
  sessionId: string,
  requestId?: string,
): { messages: ChatMessage[]; index: number } {
  const copy = [...messages];
  const lastIdx = copy.length - 1;
  if (
    lastIdx >= 0 &&
    copy[lastIdx].role === "assistant" &&
    (!requestId || !copy[lastIdx].request_id || copy[lastIdx].request_id === requestId)
  ) {
    return { messages: copy, index: lastIdx };
  }
  const created: ChatMessage = {
    id: requestId ? `asst_${requestId}` : `asst_${Date.now()}_${copy.length}`,
    session_id: sessionId,
    role: "assistant",
    content: "",
    parts: [],
    created_at: Date.now(),
    request_id: requestId,
  };
  copy.push(created);
  return { messages: copy, index: copy.length - 1 };
}

export function reduceSessionEvent(
  state: SessionStreamState,
  envelope: GatewayEventEnvelope,
): SessionStreamState {
  if (envelope.seq > 0 && envelope.seq <= state.lastSeq) {
    return state;
  }
  const nextSeq = envelope.seq > state.lastSeq ? envelope.seq : state.lastSeq;
  const p = envelope.payload || {};
  const requestId = typeof p.request_id === "string" ? p.request_id : undefined;

  switch (envelope.event) {
    case "run.started":
      return {
        ...state,
        status: "running",
        lastSeq: nextSeq,
        lastError: null,
      };

    case "text.delta": {
      const delta = String(p.delta ?? p.text ?? "");
      if (!delta) return { ...state, lastSeq: nextSeq };
      const { messages, index } = ensureStreamingAssistant(state.messages, state.sessionId, requestId);
      const target = { ...messages[index] };
      target.content = target.content + delta;
      const parts: MessagePart[] = [...target.parts];
      const lastPart = parts[parts.length - 1];
      if (lastPart && lastPart.type === "text") {
        parts[parts.length - 1] = { type: "text", text: lastPart.text + delta };
      } else {
        parts.push({ type: "text", text: delta });
      }
      target.parts = parts;
      messages[index] = target;
      return { ...state, status: "running", lastSeq: nextSeq, messages };
    }

    case "thinking.delta": {
      const delta = String(p.delta ?? p.text ?? "");
      if (!delta) return { ...state, lastSeq: nextSeq };
      const { messages, index } = ensureStreamingAssistant(state.messages, state.sessionId, requestId);
      const target = { ...messages[index] };
      const parts: MessagePart[] = [...target.parts];
      const lastPart = parts[parts.length - 1];
      if (lastPart && lastPart.type === "thinking") {
        parts[parts.length - 1] = { ...lastPart, text: lastPart.text + delta, streaming: true };
      } else {
        parts.push({ type: "thinking", text: delta, streaming: true });
      }
      target.parts = parts;
      messages[index] = target;
      return { ...state, status: "running", lastSeq: nextSeq, messages };
    }

    case "tool.started":
    case "tool.completed":
    case "tool.failed": {
      const callId = String(p.call_id ?? p.callId ?? `call_${nextSeq}`);
      const toolName = String(p.tool ?? p.tool_name ?? p.name ?? "tool");
      const status =
        envelope.event === "tool.started"
          ? "running"
          : envelope.event === "tool.completed"
            ? "completed"
            : "failed";
      const { messages, index } = ensureStreamingAssistant(state.messages, state.sessionId, requestId);
      const target = { ...messages[index] };
      const parts: MessagePart[] = [...target.parts];
      const existingIdx = parts.findIndex((part) => part.type === "tool" && part.callId === callId);
      const nextTool: ToolCallPart = {
        type: "tool",
        callId,
        toolName,
        status,
        args: (p.args ?? p.arguments) as Record<string, unknown> | undefined,
        output: p.output ?? p.result,
        error: typeof p.error === "string" ? p.error : undefined,
        durationMs: typeof p.duration_ms === "number" ? p.duration_ms : undefined,
      };
      if (existingIdx >= 0) {
        parts[existingIdx] = { ...(parts[existingIdx] as ToolCallPart), ...nextTool };
      } else {
        parts.push(nextTool);
      }
      target.parts = parts;
      messages[index] = target;
      return { ...state, lastSeq: nextSeq, messages };
    }

    case "approval.requested": {
      const approval: ApprovalPart = {
        type: "approval",
        approvalId: String(p.approval_id ?? p.id ?? `apr_${nextSeq}`),
        toolName: String(p.tool_name ?? p.tool ?? "tool"),
        prompt: String(p.prompt ?? "Approval required"),
        status: "pending",
      };
      const exists = state.pendingApprovals.some((a) => a.approvalId === approval.approvalId);
      return {
        ...state,
        status: "awaiting_approval",
        lastSeq: nextSeq,
        pendingApprovals: exists ? state.pendingApprovals : [...state.pendingApprovals, approval],
      };
    }

    case "approval.resolved": {
      const approvalId = String(p.approval_id ?? p.id ?? "");
      const remaining = state.pendingApprovals.filter((a) => a.approvalId !== approvalId);
      return {
        ...state,
        status: remaining.length > 0 ? "awaiting_approval" : "running",
        lastSeq: nextSeq,
        pendingApprovals: remaining,
      };
    }

    case "run.completed":
      return {
        ...state,
        status: "completed",
        lastSeq: nextSeq,
      };

    case "run.failed":
      return {
        ...state,
        status: "failed",
        lastSeq: nextSeq,
        lastError: String(p.error ?? "Run failed"),
      };

    default:
      return { ...state, lastSeq: nextSeq };
  }
}
