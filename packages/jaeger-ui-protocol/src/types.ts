/**
 * @jaeger/ui-protocol: Canonical Gateway wire types (versioned, zero-DOM).
 */

export const PROTOCOL_VERSION = 1 as const;

export type RunStatus = "idle" | "queued" | "running" | "awaiting_approval" | "completed" | "failed" | "cancelled";

export type ToolCallStatus = "pending" | "running" | "completed" | "failed" | "awaiting_approval";

export interface SessionSummary {
  session_id: string;
  title: string;
  workspace?: string;
  status: RunStatus;
  created_at: number;
  updated_at: number;
  unread_count?: number;
}

export interface TextPart {
  type: "text";
  text: string;
}

export interface ThinkingPart {
  type: "thinking";
  text: string;
  durationMs?: number;
  streaming?: boolean;
}

export interface ToolCallPart {
  type: "tool";
  callId: string;
  toolName: string;
  status: ToolCallStatus;
  args?: Record<string, unknown>;
  output?: unknown;
  error?: string;
  durationMs?: number;
}

export interface ApprovalPart {
  type: "approval";
  approvalId: string;
  toolName: string;
  prompt: string;
  status: "pending" | "approved" | "denied";
  note?: string;
}

export type MessagePart = TextPart | ThinkingPart | ToolCallPart | ApprovalPart;

export interface ChatMessage {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  parts: MessagePart[];
  created_at: number;
  request_id?: string;
  optimistic?: boolean;
}

export interface GatewayEventEnvelope {
  seq: number;
  event: string;
  session_id?: string;
  payload: Record<string, unknown>;
  timestamp?: number;
}

export interface SessionStreamState {
  protocolVersion: typeof PROTOCOL_VERSION;
  sessionId: string;
  status: RunStatus;
  lastSeq: number;
  messages: ChatMessage[];
  pendingApprovals: ApprovalPart[];
  lastError: string | null;
}
