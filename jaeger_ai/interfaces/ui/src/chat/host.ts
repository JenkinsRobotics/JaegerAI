import type { Agent } from "../api/types";
/* Chat pane seam. FROZEN with Jaeger IDE Chat (2026-10-17). Mirror only; do
 * not extend here. The shared chat widget (a port of the VS Code 1.142 chat
 * widget, packages/jaeger-chat-ui + jaeger-chat-gateway) mounts through
 * `ChatPaneMount`. The renderer in this folder is a minimal stand-in for the
 * mock screenshot.
 *
 * Contract: `mount(el, host, opts) => dispose`. It is framework-free and owns
 * `el` and nothing else. */

export type HostKind = "vscode" | "native" | "web";

export type ToolInvocationState = "streaming" | "waitingForConfirmation" | "executing" | "completed" | "cancelled" | "failed" | "denied" | "rejected" | "unsupported" | "unknown";

export type ChatPart =
  | { kind: "markdownContent"; text: string }
  | { kind: "thinking"; text: string; durationMs?: number }
  | { kind: "toolInvocation"; callId: string; toolName: string; input: unknown; state: ToolInvocationState; output?: unknown }
  | { kind: "confirmation"; callId: string; title: string; message: string }
  | { kind: "progress"; message: string }
  | { kind: "error"; message: string }
  | { kind: "warning"; message: string }
  /** PROPOSED addition (not yet in the frozen IDE Chat contract): an answered
   * question widget. Renders the question plus its options with the chosen
   * one highlighted. */
  | { kind: "question"; callId: string; title: string; options: Array<{ id: string; label: string }>; chosenId?: string }
  /** Centered hand-off marker. `agents` set means a grouped "Messaged X and Y". */
  | { kind: "handoff"; status?: string; handoffId: string; agentId: string; agentName: string; count: number; direction: "to" | "from"; agents?: Array<{ id: string; name: string }> };

export type ChatPartKind = ChatPart["kind"];

export interface ChatAttachment {
  name: string;
  mimeType: string;
  uri?: string;
  data?: string;
}

export interface StartTurnRequest {
  sessionId: string;
  turnId: string;
  model?: string;
  mode?: string;
  message: string;
  attachments?: ChatAttachment[];
  onAccepted?: () => void;
  draftFileIds?: string[];
  draftBody?: string;
  quoteKey?: string;
}

export type TurnState = "complete" | "cancelled" | "failed" | "needs_input" | "unknown";

export interface TurnHandle {
  cancel(): void;
  done: Promise<{ state: TurnState }>;
}

export interface ChatTurn {
  turnId: string;
  message: string;
  parts: ChatPart[];
  state: "pending" | TurnState;
  /** PROPOSED addition: epoch ms the turn started, for day/time separators. */
  createdAt?: number;
}

export interface ChatSessionSummary {
  id: string;
  title: string;
  agentId?: string;
  updatedAt?: number;
  preview?: string;
}

export interface ChatSession extends ChatSessionSummary {
  turns: ChatTurn[];
}

export interface ChatModel { id: string; name: string; provider?: string }
export interface ChatAgentRef { id: string; name: string; description?: string }
export interface ChatConfig { defaultModel?: string; defaultMode?: string; [key: string]: unknown }

export interface ChatHost {
  readonly modelSettings?: import("../api/source").ModelSettings;
  readonly kind: HostKind;
  getConfig(): Promise<ChatConfig>;
  listModels(): Promise<ChatModel[]>;
  /** Parts stream through `onPart`. markdownContent/thinking append to the open
   * part of that kind; toolInvocation/confirmation with a known callId replace
   * it; everything else appends. */
  startTurn(request: StartTurnRequest, onPart: (part: ChatPart) => void): TurnHandle;
  respondToConfirmation(turnId: string, callId: string, decision: "approve" | "deny", scope?: "once" | "session"): Promise<void>;
  sessions: {
    list(): Promise<ChatSessionSummary[]>;
    load(id: string): Promise<ChatSession>;
    save(session: ChatSession): Promise<void>;
    delete(id: string): Promise<void>;
  };
  openExternal(url: string): void;
  openFile?(path: string): void;
  copy(text: string): Promise<void>;
  onThemeChanged?(cb: () => void): () => void;
  /** For @ mentions. */
  listAgents?(): Promise<ChatAgentRef[]>;
  onSessionEvent?(cb: (event: { sessionId: string; type: string }) => void): () => void;
  openHandoffReply?(handoffId: string): void;
  openHandoff?(handoffId: string): void;
  /** PROPOSED addition: the chat header's agent pill opens that agent's details. */
  openDetails?(agentId: string): void;
  capabilities: { voice: boolean };
}

export interface ChatPaneOptions {
  agents?: Agent[];
  sessionId?: string;
}

export type ChatPaneMount = (el: HTMLElement, host: ChatHost, opts: ChatPaneOptions) => (() => void) & { updateAgents?: (agents: Agent[]) => void };

/** Apply the onPart contract to a part list. */
export function applyPart(parts: ChatPart[], part: ChatPart): ChatPart[] {
  if (part.kind === "handoff") {
    const index = parts.findIndex((p) => p.kind === "handoff" && p.handoffId === part.handoffId && p.direction === part.direction);
    if (index >= 0) return parts.map((p, i) => i === index && !(p.kind === "handoff" && p.status === "delivered" && part.status !== "delivered") ? part : p);
  }
  const last = parts[parts.length - 1];
  if ((part.kind === "markdownContent" || part.kind === "thinking") && last?.kind === part.kind) {
    return [...parts.slice(0, -1), { ...last, ...part, text: last.text + part.text } as ChatPart];
  }
  if (part.kind === "toolInvocation" || part.kind === "confirmation") {
    const index = parts.findIndex((p) => p.kind === part.kind && p.callId === part.callId);
    if (index >= 0) return parts.map((p, i) => (i === index ? ({ ...p, ...part } as ChatPart) : p));
  }
  return [...parts, part];
}
