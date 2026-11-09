import type { Agent } from "../api/types";
/* Shared UI chat-host seam for the browser and native shell. Gateway transport
 * and recovery live in typed adapters; this renderer does not own execution.
 * Keep live and persisted part mappings aligned when extending the contract.
 * The IDE extension is a separate surface and is not modified by this module. */

export type HostKind = "vscode" | "native" | "web";

export type ToolInvocationState = "streaming" | "waitingForConfirmation" | "executing" | "completed" | "cancelled" | "failed" | "denied" | "rejected" | "unsupported" | "unknown";
export type AssistantContentRole = "provisional" | "commentary" | "final";

export type ChatPart =
  | { kind: "userGuidance"; text: string; steeringId: string }
  | {kind:"plan";plan:Array<{step:string;status:"pending"|"in_progress"|"completed"}>;explanation:string}
  | {kind:"checkpoint";text:string}
  | {kind:"sources";sources:Array<{kind:"url"|"file";location:string;title?:string}>}
  | {kind:"searchCount";searches:number;completed:number;failed:number}
  | {kind:"followUps";prompts:string[]}
  | {kind:"modelIdentity";actualModel:string|null;scope:string}
  | { kind: "modelContext"; outline: import("./modelContext").ModelContextOutline }
  | { kind: "knowledgeContext"; documents: { id: string; revision: number; digest: string; title: string }[] }
  | { kind: "markdownContent"; text: string; role?: AssistantContentRole; itemId?: string; authoritativeEmpty?: true }
  | { kind: "thinking"; text: string; durationMs?: number }
  | { kind: "toolInvocation"; callId: string; approvalId?: string; requestId?: string; executionReceipt?: boolean; toolName: string; input: unknown; state: ToolInvocationState; output?: unknown; summary?: string }
  | { kind: "confirmation"; callId: string; requestId?: string; toolCallId?: string; title: string; message: string; decision?: "approve" | "deny" }
  | { kind: "progress"; message: string }
  | { kind: "error"; message: string }
  /** `noticeId`: a status notice that a later notice with the same id replaces in place (e.g. Stop). */
  | { kind: "warning"; message: string; noticeId?: string }
  /** PROPOSED addition (not yet in the frozen IDE Chat contract): an answered
   * question widget. Renders the question plus its options with the chosen
   * one highlighted. */
  | { kind: "question"; callId: string; title: string; options: Array<{ id: string; label: string }>; chosenId?: string;
      /** Server clarify form (GB-033): answerable only while pending, at this revision. */
      revision?: number; status?: "pending" | "answered" | "cancelled" | "expired"; sessionId?: string }
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
  fastLane?: boolean;
  attachments?: ChatAttachment[];
  onAccepted?: () => void;
  draftFileIds?: string[];
  draftBody?: string;
  quoteKey?: string;
}

export type TurnState = "complete" | "cancelled" | "failed" | "needs_input" | "unknown";
export type ClarifyAnswerResult = { status: "answered"; answer: string } | { status: "cancelled" | "expired" };

export interface TurnHandle {
  cancel(): void;
  done: Promise<{ state: TurnState }>;
}

export interface ChatTurn {
  channelReply?:{messageId:number;channel:string;recipient:string};
  turnId: string;
  /** Authoritative admission identity; never a message/rendering ID. */
  requestId?: string;
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
  readonly taskArtifacts?:import("../api/source").TaskArtifacts;
  readonly sessionFiles?: import("../api/source").SessionFiles;
  readonly sessionQueue?: import("../api/source").SessionQueue;
  readonly messageReadState?: import("../api/source").JaegerSource["messageReadState"];
  readonly messageReactions?: import("../api/source").JaegerSource["messageReactions"];
  readonly modelSettings?: import("../api/source").ModelSettings;
  readonly runtimeAutonomy?: import("../api/source").JaegerSource["runtimeAutonomy"];
  readonly setRuntimeAutonomy?: import("../api/source").JaegerSource["setRuntimeAutonomy"];
  readonly runtimeTier?: import("../api/source").JaegerSource["runtimeTier"];
  readonly setRuntimeTier?: import("../api/source").JaegerSource["setRuntimeTier"];
  readonly kind: HostKind;
  getConfig(): Promise<ChatConfig>;
  listModels(): Promise<ChatModel[]>;
  /** Parts stream through `onPart`. markdownContent/thinking append to the open
   * part of that kind; toolInvocation/confirmation with a known callId replace
   * it; everything else appends. */
  startTurn(request: StartTurnRequest, onPart: (part: ChatPart) => void): TurnHandle;
  respondToConfirmation(turnId: string, callId: string, decision: "approve" | "deny", scope?: "once" | "session"): Promise<void>;
  /** Durable lookup used to reconcile approval cards after a reload or a decision from another surface. */
  approvalStatus?(approvalId: string): Promise<{ approval_id: string; status: string; decision?: string }>;
  /** Answer a server clarify form once (GB-033). Absent: the card is display-only. */
  answerClarify?(sessionId: string, clarifyId: string, revision: number, response: string): Promise<ClarifyAnswerResult>;
  /** Recover server forms and terminal outcomes after navigation or reload. */
  clarifications?(sessionId: string): Promise<import("../api/source").ClarificationSnapshot[]>;
  /** Read the original durable status after an uncertain answer acknowledgement. */
  clarificationStatus?(sessionId: string, clarifyId: string): Promise<import("../api/source").ClarificationSnapshot>;
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
  openTaskArtifacts?(taskId:string):void;
  /** PROPOSED addition: the chat header's agent pill opens that agent's details. */
  openDetails?(agentId: string): void;
  capabilities: { voice: boolean };
}

export interface ChatPaneOptions {
  onAvatarState?: (state: import("../avatar/avatar").ClipState) => void;
  agents?: Agent[];
  sessionId?: string;
  /** The selected durable session disappeared while this pane was mounted. */
  onSessionMissing?: (sessionId: string) => void;
}

export type ChatPaneMount = (el: HTMLElement, host: ChatHost, opts: ChatPaneOptions) => (() => void) & { updateAgents?: (agents: Agent[]) => void };

/** Gateway errors retain their transport prefix, so classify by the durable error message. */
export function isSessionMissingError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return /\bsession not found\b/i.test(message);
}

/** Apply the onPart contract to a part list. */
export function applyPart(parts: ChatPart[], part: ChatPart): ChatPart[] {
  // Both parts of a delayed approval request share the same stale-call guard.
  // Missing legacy request IDs must not rewind a receipt; known different IDs
  // describe separate requests even when a producer reuses the call ID.
  const hasTerminalReceipt=(callId:string,requestId?:string)=>parts.some(p=>p.kind==="toolInvocation" && p.callId===callId &&
    !(p.requestId && requestId && p.requestId!==requestId) && p.executionReceipt!==false &&
    !["streaming","waitingForConfirmation","executing"].includes(p.state));
  if(part.kind==="confirmation" && !part.decision && part.toolCallId && hasTerminalReceipt(part.toolCallId,part.requestId))return parts;
  if(part.kind==="toolInvocation" && part.state==="waitingForConfirmation" && part.approvalId){
    if(hasTerminalReceipt(part.callId,part.requestId))return parts;
    const card=parts.find(p=>p.kind==="confirmation" && p.callId===part.approvalId);
    if(card)return parts; // Replay cannot reopen a resolved or superseded wait.
  }
  if(part.kind==="confirmation" && !part.decision && parts.some(p=>p.kind==="confirmation" && p.callId===part.callId))return parts;
  // Approval receipts close permission waits, not tool execution. Correlate using
  // the original card, since the producer need not repeat the tool call ID.
  if(part.kind==="confirmation" && part.decision && !part.title){
    const card=parts.find((p):p is Extract<ChatPart,{kind:"confirmation"}>=>p.kind==="confirmation" && p.callId===part.callId);
    if(!card || card.decision || (part.requestId && card.requestId && card.requestId!==part.requestId) || (part.toolCallId && card.toolCallId!==part.toolCallId))return parts;
    parts=parts.map(p=>p.kind==="toolInvocation" && p.state==="waitingForConfirmation" && p.callId===card.toolCallId && p.approvalId===card.callId && p.requestId===card.requestId
      ? {...p,state:part.decision==="deny"?"denied":"unknown",summary:part.decision==="deny"?"Permission denied or closed; tool not executed by this approval.":"Permission granted; execution not yet reported."}:p);
  }
  // Empty stream deltas carry no answer. Only a durable completed-empty receipt
  // may clear an observed answer; a stream's role/item ID alone is not a receipt.
  if (part.kind === "markdownContent" && part.text === "" &&
      !(part.role === "final" && part.itemId === "final" && part.authoritativeEmpty === true)) return parts;
  if (part.kind === "warning" && part.noticeId) {
    const index = parts.findIndex(p => p.kind === "warning" && p.noticeId === part.noticeId);
    if (index >= 0) return parts.map((p, i) => i === index ? part : p);
  }
  if (part.kind === "userGuidance") return parts.some(row => row.kind === "userGuidance" && row.steeringId === part.steeringId) ? parts : [...parts, part];
  if (part.kind === "knowledgeContext") { const index = parts.findIndex(p => p.kind === "knowledgeContext"); return index < 0 ? [...parts, part] : parts.map((p, i) => i === index ? part : p); }
  if (part.kind === "handoff") {
    const index = parts.findIndex((p) => p.kind === "handoff" && p.handoffId === part.handoffId && p.direction === part.direction);
    if (index >= 0) return parts.map((p, i) => i === index && !(p.kind === "handoff" && p.status === "delivered" && part.status !== "delivered") ? part : p);
  }
  if (["plan","searchCount","followUps"].includes(part.kind)) {
    const index=parts.findIndex(p=>p.kind===part.kind);
    if(index>=0)return parts.map((p,i)=>i===index?part:p);
  }
  if (part.kind === "markdownContent" && part.role === "final" && part.itemId === "final") {
    // The terminal answer (turn.finish / request outcome) is authoritative for the whole answer: it
    // supersedes every streamed provisional AND final item, so the answer is never shown twice.
    // Commentary (text before a tool round) is a separate, earlier message and stays.
    const answer = parts.map((p, i) => p.kind === "markdownContent" && (p.role ?? "provisional") !== "commentary" ? i : -1).filter(i => i >= 0);
    if (answer.length) {
      const [first, ...rest] = answer;
      return parts.map((p, i) => i === first ? part : p).filter((_, i) => !rest.includes(i));
    }
  }
  const tail = parts[parts.length - 1];
  // A streamed final item continues by appending (below); only a new final item replaces earlier text.
  const continuesFinal = part.kind === "markdownContent" && tail?.kind === "markdownContent" && tail.role === "final" && (tail.itemId ?? "") === (part.itemId ?? "");
  if (part.kind === "markdownContent" && part.role === "final" && !continuesFinal) {
    const provisional = parts.map((p, i) => p.kind === "markdownContent" && (p.role ?? "provisional") === "provisional" ? i : -1).filter(i => i >= 0);
    if (provisional.length) {
      const [first, ...rest] = provisional;
      return parts.map((p, i) => i === first ? part : p).filter((_, i) => !rest.includes(i));
    }
    const existing = parts.findIndex(p => p.kind === "markdownContent" && p.role === "final");
    if (existing >= 0) return parts.map((p, i) => i === existing ? part : p);
  }
  if (part.kind === "toolInvocation") {
    parts = parts.map(p => p.kind === "markdownContent" && (p.role ?? "provisional") === "provisional" ? {...p, role:"commentary" as const} : p);
  }
  const last = parts[parts.length - 1];
  if (part.kind === "markdownContent" && last?.kind === "markdownContent" &&
      (part.role ?? "provisional") === (last.role ?? "provisional") && (part.itemId ?? "") === (last.itemId ?? "")) {
    return [...parts.slice(0, -1), { ...last, ...part, text: last.text + part.text }];
  }
  if (part.kind === "thinking" && last?.kind === "thinking") {
    return [...parts.slice(0, -1), { ...last, ...part, text: last.text + part.text } as ChatPart];
  }
  if (part.kind === "toolInvocation" || part.kind === "confirmation" || part.kind === "question") {
    const index = parts.findIndex((p) => p.kind === part.kind && p.callId === part.callId &&
      !(p.kind === "toolInvocation" && part.kind === "toolInvocation" && p.requestId && part.requestId && p.requestId !== part.requestId));
    if (index >= 0) return parts.map((p, i) => {
      if (i !== index) return p;
      // Resolution events carry only status; preserve the original card content.
      if (part.kind === "confirmation" && p.kind === "confirmation" && !part.title) return { ...p, decision: part.decision ?? p.decision };
      if (part.kind === "question" && p.kind === "question" && !part.title) return { ...p, status: part.status ?? p.status };
      return { ...p, ...part } as ChatPart;
    });
  }
  return [...parts, part];
}
