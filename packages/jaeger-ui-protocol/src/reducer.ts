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

function finishStreamingThinking(parts: MessagePart[]): MessagePart[] {
  let changed = false;
  const next = parts.map((part) => {
    if (part.type === "thinking" && part.streaming) {
      changed = true;
      return { ...part, streaming: false };
    }
    return part;
  });
  return changed ? next : parts;
}

function ensureStreamingAssistant(
  messages: ChatMessage[],
  sessionId: string,
  requestId?: string,
): { messages: ChatMessage[]; index: number } {
  const copy = [...messages];
  const index = requestId
    ? copy.findIndex((message) => message.role === "assistant" && message.request_id === requestId)
    : copy.length - 1;
  if (index >= 0 && copy[index].role === "assistant") return { messages: copy, index };
  const created: ChatMessage = {
    id: requestId ? `asst_${requestId}` : `asst_${Date.now()}_${copy.length}`,
    session_id: sessionId,
    role: "assistant",
    content: "",
    parts: [],
    created_at: Date.now() / 1000,
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
    case "run.started": {
      const existing = requestId && state.messages.find((message) => message.role === "user" && message.request_id === requestId);
      const recordId = typeof p.message_id === "number" ? p.message_id : undefined;
      const prompt = typeof p.prompt === "string" ? p.prompt : "";
      let messages = state.messages;
      if (existing && recordId !== undefined && existing.record_id === undefined) {
        messages = messages.map((message) => message === existing ? { ...message, record_id: recordId } : message);
      } else if (requestId && prompt && !existing) messages = [...messages, {
        id: `opt_${requestId}`,
        session_id: state.sessionId,
        role: "user",
        content: prompt,
        parts: [{ type: "text", text: prompt }],
        created_at: typeof p.created_at === "number" ? p.created_at : Date.now() / 1000,
        request_id: requestId,
        record_id: recordId,
      }];
      return { ...state, status: "running", lastSeq: nextSeq, lastError: null, messages };
    }

    case "text.delta": {
      const delta = String(p.delta ?? p.text ?? "");
      if (!delta) return { ...state, lastSeq: nextSeq };
      const { messages, index } = ensureStreamingAssistant(state.messages, state.sessionId, requestId);
      const target = { ...messages[index] };
      target.content = target.content + delta;
      const parts: MessagePart[] = [...finishStreamingThinking(target.parts)];
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
      const parts: MessagePart[] = [...finishStreamingThinking(target.parts)];
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

    case "run.completed": {
      const content = typeof p.content === "string" ? p.content : "";
      let messages = state.messages;
      const existingIdx = requestId
        ? messages.findIndex((message) => message.role === "assistant" && message.request_id === requestId)
        : messages.length - 1;
      if (content || (existingIdx >= 0 && messages[existingIdx].role === "assistant")) {
        const assistant = ensureStreamingAssistant(messages, state.sessionId, requestId);
        messages = assistant.messages;
        const target = messages[assistant.index];
        let parts = finishStreamingThinking(target.parts).map((part) =>
          part.type === "tool" && part.status === "running"
            ? { ...part, status: "completed" as const }
            : part,
        );
        let nextContent = target.content;
        if (content && !target.content.trimEnd().endsWith(content.trimEnd())) {
          nextContent = target.content ? `${target.content}\n\n${content}` : content;
          parts = [...parts, { type: "text", text: content }];
        }
        messages[assistant.index] = { ...target, content: nextContent, parts };
      }
      return { ...state, status: "completed", lastSeq: nextSeq, messages };
    }

    case "run.failed": {
      const error = String(p.error ?? "Run failed");
      const content = String(p.content ?? error);
      const { messages, index } = ensureStreamingAssistant(state.messages, state.sessionId, requestId);
      const target = messages[index];
      const parts: MessagePart[] = finishStreamingThinking(target.parts).map((part) =>
        part.type === "tool" && part.status === "running"
          ? { ...part, status: "failed", error: "Interrupted before a result was confirmed." }
          : part,
      );
      messages[index] = {
        ...target,
        content: target.content ? `${target.content}\n\n${content}` : content,
        parts: [...parts, { type: "text", text: content }],
      };
      return {
        ...state,
        status: "failed",
        lastSeq: nextSeq,
        lastError: error,
        messages,
      };
    }

    default:
      return { ...state, lastSeq: nextSeq };
  }
}
