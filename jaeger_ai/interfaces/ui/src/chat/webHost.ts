import { readIntent, saveIntent, settleIntent, type SendIntent } from "./sendJournal";
import { requestOutcome } from "./requestOutcome";
/* WebHost: ChatHost for the browser. Data comes from a JaegerSource (live =
 * same-origin /v1 and /api fetches; mock = dev-only sample data). Failures
 * surface to the caller; there is no silent fallback. */
import type { JaegerSource } from "../api/source";
import type { PersistedPart, SessionMessage } from "../api/types";
import { bytesUploadEnabled, UPLOAD_MAX_BYTES, UPLOAD_TOO_LARGE, type RejectedAttachment } from "./composer";
import { followTurn } from "./followTurn";
import type { HomeSessions } from "./homeSession";
import type { ChatAgentRef, ChatHost, ChatPart, ChatSession, HostKind, StartTurnRequest, ToolInvocationState, TurnHandle, TurnState } from "./host";
import type { HostAttachment, HostCapabilities } from "./hostH8";

const KEY = (id: string) => `jaeger.ui.session.${id}`;

const toolState = (s?: string): ToolInvocationState => ["done", "completed"].includes(s ?? "") ? "completed" : ["error", "failed"].includes(s ?? "") ? "failed" : ["denied", "rejected", "cancelled", "unsupported", "unknown"].includes(s ?? "") ? s as ToolInvocationState : "executing";

/** A pending approval holds its tool: matched on tool + target (call_id is usually null). */
function holdApprovedTools(source: PersistedPart[], parts: ChatPart[]) {
  for (const a of source) {
    if (a.type !== "approval" || (a.state ?? a.status) !== "pending") continue;
    const tool = parts.find((p): p is Extract<ChatPart, { kind: "toolInvocation" }> => p.kind === "toolInvocation" && p.toolName === a.tool
      && p.state === "executing" && (!a.target || JSON.stringify(p.input ?? "").includes(a.target)));
    if (tool) tool.state = "waitingForConfirmation";
  }
}

function persistedToPart(p: PersistedPart, agentName: (id: string) => string): ChatPart | null {
  switch (p.type) {
    case "text": return p.text ? { kind: "markdownContent", text: p.text } : null;
    case "reasoning": return { kind: "thinking", text: p.text ?? "", durationMs: p.duration_ms };
    case "tool": return {
      kind: "toolInvocation", callId: String(p.call_id ?? ""), toolName: String(p.tool ?? "tool"), input: p.input ?? null,
      state: toolState(p.state ?? p.status), output: p.output,
    };
    // Pending: the card. Decided: the tool part carries the outcome; no card.
    case "approval": return (p.state ?? p.status) === "pending"
      ? { kind: "confirmation", callId: p.approval_id, title: p.tool ? `Run ${p.tool}?` : "Approval needed", message: p.target ?? "" }
      : null;
    case "handoff": {
      const agentId = String(p.agent_id ?? "");
      return { kind: "handoff", status: p.status ?? "unverified", handoffId: String(p.handoff_id ?? ""), agentId, agentName: p.agent_name || agentName(agentId), count: 1, direction: p.direction };
    }
    default: return null;
  }
}

const epochMs = (m: SessionMessage) => {
  const seconds = Number(m.timestamp ?? m.created_at);
  return Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : undefined;
};

export function messagesToTurns(messages: SessionMessage[] = [], agentName: (id: string) => string = (id) => id): ChatSession["turns"] {
  const turns: ChatSession["turns"] = [];
  for (const m of messages) {
    if (m.role === "user") {
      turns.push({ turnId: m.request_id != null ? String(m.request_id) : m.id != null ? String(m.id) : `t${turns.length}`, requestId: m.request_id, message: m.content ?? "", parts: [], state: "complete", createdAt: epochMs(m) });
    } else if (m.role === "assistant") {
      // A reply with no user turn before it (proactive note, relayed report) still shows.
      if (!turns.length || m.request_id && turns.at(-1)?.requestId !== m.request_id) turns.push({ turnId: m.request_id ?? `t${turns.length}`, requestId: m.request_id, message: "", parts: [], state: "complete", createdAt: epochMs(m) });
      const parts = m.parts?.length
        ? m.parts.map((p) => persistedToPart(p, agentName)).filter((p): p is ChatPart => p !== null)
        : [{ kind: "markdownContent" as const, text: m.content ?? "" }];
      if (m.parts?.length) holdApprovedTools(m.parts, parts);
      turns[turns.length - 1].parts.push(...parts);
    }
  }
  return turns;
}

const message = (error: unknown) => String((error as Error)?.message ?? error);

export class WebHost implements ChatHost {
  readonly kind: HostKind = "web";
  capabilities: HostCapabilities = { voice: false };
  /** Set by the app: the agent's one home chat, its pages and history (Grok-style sessions). */
  home?: HomeSessions;
  /** Set by the app: the header menu's History opens the agent's older chats. */
  openHistory?: (agentId: string) => void;
  /** A home-chat page reports the stream cursor it was read at. */
  noteCursor(sessionId: string, eventId: number) { this.advance(sessionId, eventId); }
  /** Set by the app: a post's "Open chat" shows that (child) chat read-only. */
  openChat?: (sessionId: string) => void;
  /** Set by the app: a handoff marker opens the specialist's side of it. */
  openHandoffReply?: (handoffId: string) => void;
  openHandoff?: (handoffId: string) => void;
  /** Set by the app: the header pill opens the agent's details panel. */
  openDetails?: (agentId: string) => void;
  /** Bytes upload route: unknown until first tried; false after a 404/405 (feature-detect). */
  private bytesUpload?: boolean;
  private agentNames = new Map<string, string>();
  /** Last SSE event id seen per session; the stream never resumes behind it. */
  private readonly cursors = new Map<string, number>();

  constructor(protected readonly source: JaegerSource, private readonly backoffMs?: number[]) {}

  setAgentNames(names: Map<string, string>) { this.agentNames = names; }
  private agentName = (id: string) => this.agentNames.get(id) ?? id;

  cursorFor(sessionId: string) { return this.cursors.get(sessionId) ?? 0; }
  private advance(sessionId: string, eventId: number) {
    if (eventId > this.cursorFor(sessionId)) this.cursors.set(sessionId, eventId);
  }

  async getConfig() { return { defaultMode: "agent" }; }

  /** POST each picked file to /v1/sessions/{id}/attachments; the ids that registered go with the turn. */
  private async registerAttachments(request: StartTurnRequest, onPart: (part: ChatPart) => void): Promise<{ ids: string[]; draftFileIds: string[] }> {
    const ids: string[] = [];
    const draftFileIds: string[] = [];
    const rejected: RejectedAttachment[] = [];
    // H8 widens ChatAttachment with path/size; read through the local mirror until it's vendored.
    for (const [index, file] of ((request.attachments ?? []) as HostAttachment[]).entries()) {
      // Bytes first (the upload route, 417d8a0c), path as the fallback for gateways without it (404/405).
      if (typeof file.data === "string" && this.source.uploadAttachment && bytesUploadEnabled() && this.bytesUpload !== false) {
        if (Math.floor((file.data.length * 3) / 4) > UPLOAD_MAX_BYTES) { rejected.push({ name: file.name, reason: UPLOAD_TOO_LARGE }); continue; }
        try {
          const row = await this.source.uploadAttachment(request.sessionId, { name: file.name, mime: file.mimeType, data_base64: file.data }, `upload-${request.turnId}-${index}`);
          this.bytesUpload = true;
          ids.push(row.attachment_id);
          if (request.draftFileIds?.[index]) draftFileIds.push(request.draftFileIds[index]);
          continue;
        } catch (error) {
          const status = (error as { status?: number }).status;
          if (status === 413) { rejected.push({ name: file.name, reason: UPLOAD_TOO_LARGE }); continue; }
          // 404/405: this gateway has no bytes route; remember it and treat the file as path-less.
          if (status === 404 || status === 405) this.bytesUpload = false;
          else { rejected.push({ name: file.name, reason: message(error) }); continue; }
        }
      }
      if (!file.path) { rejected.push({ name: file.name, reason: "no file path from this window" }); continue; }
      try {
        const row = await this.source.addAttachment(request.sessionId, { path: file.path, filename: file.name, mime_type: file.mimeType });
        ids.push(row.attachment_id);
        if (request.draftFileIds?.[index]) draftFileIds.push(request.draftFileIds[index]);
      } catch (error) {
        rejected.push({ name: file.name, path: file.path, reason: message(error) });
      }
    }
    if (rejected.length) {
      onPart({ kind: "warning", message: `Not attached: ${rejected.map((r) => `${r.name} (${r.reason})`).join(", ")}.` });
      this.onAttachmentsRejected?.(request.turnId, rejected);
    }
    return { ids, draftFileIds };
  }
  /** The chat view puts refused files back on the composer as error chips. */
  onAttachmentsRejected?: (turnId: string, rejected: RejectedAttachment[]) => void;
  get modelSettings() { return this.source.modelSettings; }
  get messageReactions() { return this.source.messageReactions; }
  get sessionQueue() { return this.source.sessionQueue; }
  async listModels() {
    const inventory = await this.source.modelSettings?.inventory();
    return inventory?.providers.filter(p => p.reachable).flatMap(p => p.models.filter(m => m.available !== false).map(m => ({ id: `@${p.id}:${m.id}`, name: m.id, provider: p.id }))) ?? [];
  }

  startTurn(request: StartTurnRequest, onPart: (part: ChatPart) => void): TurnHandle {
    const controller = new AbortController();
    const requestId = request.turnId;
    let admitted = false;
    let cancelRequested = false;
    let admittedRequestId = requestId;
    const requestCancel = () => {
      onPart({ kind: "progress", message: "Stopping… Waiting for Gateway confirmation." });
      void this.source.cancel(request.sessionId, admittedRequestId).catch((error: unknown) => {
        onPart({ kind: "warning", message: `Stop was not confirmed: ${message(error)}. Still observing this request.` });
      });
    };
    const done = (async (): Promise<{ state: TurnState }> => {
      // The gateway attaches workspace files by path. Host-picked files (H8 `path`) are registered first;
      // pasted or dropped ones have no path, so they're named in a warning instead of silently dropped.
      let intent: SendIntent;
      try {
        const prior = readIntent(request.sessionId);
        if (prior) throw new Error(`Request ${prior.requestId} needs reconciliation before another turn`);
        intent = { version: 1, sessionId: request.sessionId, requestId, text: request.message, draftBody: request.draftBody, quoteKey: request.quoteKey, attachmentIds: [], draftFileIds: request.draftFileIds ?? [], phase: "preparing" };
        saveIntent(intent);
      } catch (error) {
        onPart({ kind: "error", message: `Not sent: ${message(error)}` });
        return { state: "unknown" };
      }
      const registered = await this.registerAttachments(request, onPart);
      const attachmentIds = registered.ids;
      if (cancelRequested) {
        settleIntent(request.sessionId, requestId);
        onPart({ kind: "progress", message: "Stopped before dispatch; no turn was submitted." });
        return { state: "cancelled" };
      }
      intent = { ...intent, attachmentIds, draftFileIds: registered.draftFileIds, phase: "submitting" };
      try { saveIntent(intent); } catch (error) {
        onPart({ kind: "error", message: `Not sent: could not preserve request (${message(error)})` });
        return { state: "unknown" };
      }
      let receipt;
      try {
        receipt = await this.source.send(request.sessionId, request.message, requestId, attachmentIds);
      } catch (error) {
        // A lost HTTP reply says nothing about admission. Query the same ID,
        // never call send again. A 404 can race admission and remains uncertain.
        try {
          const row = await this.source.requestStatus?.(request.sessionId, requestId);
          if (row && row.request_id === requestId && row.session_id === request.sessionId) {
            request.onAccepted?.();
            const state = requestOutcome(row, onPart);
            if (state) {
              if (state !== "unknown") settleIntent(request.sessionId, requestId);
              return { state };
            }
            receipt = { request_id: row.request_id, turn_id: row.turn_id };
          }
        } catch { /* retain uncertainty below */ }
        if (!receipt) {
          onPart({ kind: "warning", message: `Acceptance is unknown (${message(error)}). Request ${requestId} is preserved; do not resend.` });
          return { state: "unknown" };
        }
      }
      intent = { ...intent, phase: "accepted" };
      try { saveIntent(intent); } catch { /* pre-dispatch identity remains durable */ }
      request.onAccepted?.();
      admittedRequestId = receipt.request_id ?? requestId;
      admitted = true;
      if (cancelRequested) requestCancel();
      const start = typeof receipt.start_event_id === "number" ? receipt.start_event_id - 1 : 0;
      const outcome = await followTurn({
        source: this.source,
        sessionId: request.sessionId,
        requestId: receipt.request_id ?? requestId,
        turnId: receipt.turn_id,
        cursor: Math.max(start, this.cursorFor(request.sessionId)),
        signal: controller.signal,
        onPart,
        onCursor: (id) => this.advance(request.sessionId, id),
        agentName: this.agentName,
        backoffMs: this.backoffMs,
      });
      if (outcome.state !== "unknown") settleIntent(request.sessionId, requestId);
      return outcome;
    })();
    return {
      cancel: () => {
        if (cancelRequested) return;
        cancelRequested = true;
        if (admitted) requestCancel();
        // Keep observing the original request. A client-side stream abort is
        // not proof that execution stopped (and must not unlock another send).
      },
      done,
    };
  }

  pendingIntent(sessionId: string) { return readIntent(sessionId); }

  async findPendingIntent(sessionId: string, unresolvedRequestId?: string): Promise<SendIntent | undefined> {
    const local = this.pendingIntent(sessionId);
    if (local) return local;
    const control = await this.source?.sessionControl?.(sessionId);
    const latest = unresolvedRequestId ? { request_id: unresolvedRequestId, status: "execution_unknown" } : control?.latest_request;
    if (!latest || !["admitted", "running", "awaiting_approval", "cancelling", "execution_unknown"].includes(latest.status)) return;
    const row = await this.source.requestStatus?.(sessionId, latest.request_id);
    if (!row || row.session_id !== sessionId || row.request_id !== latest.request_id) throw new Error("Saved request identity could not be verified");
    // Cross-device/background work has no authority to clear this device's draft.
    return { version: 1, deviceDraft: false, sessionId, requestId: row.request_id,
      text: row.input_text ?? "", attachmentIds: [], phase: "accepted" };
  }

  /** Observe an existing journaled request. Never calls send or reuploads files. */
  recoverTurn(intent: SendIntent, onPart: (part: ChatPart) => void, onAccepted?: () => void): TurnHandle {
    const controller = new AbortController();
    const done = (async (): Promise<{ state: TurnState }> => {
      try {
        const row = await this.source.requestStatus?.(intent.sessionId, intent.requestId);
        if (!row || row.request_id !== intent.requestId || row.session_id !== intent.sessionId) throw new Error("No matching receipt");
        onAccepted?.();
        const settled = requestOutcome(row, onPart);
        const outcome = settled ? { state: settled } : await followTurn({
          source: this.source, sessionId: intent.sessionId, requestId: intent.requestId,
          turnId: row.turn_id, cursor: 0, signal: controller.signal, onPart,
          backoffMs: this.backoffMs, agentName: this.agentName,
        });
        if (outcome.state !== "unknown") settleIntent(intent.sessionId, intent.requestId);
        return outcome;
      } catch {
        onPart({ kind: "warning", message: `Request ${intent.requestId} remains unconfirmed. Nothing was resent.` });
        return { state: "unknown" };
      }
    })();
    return { done, cancel: () => {
      void this.source.cancel(intent.sessionId, intent.requestId).catch(error => onPart({ kind: "warning", message: `Stop unconfirmed: ${message(error)}` }));
    } };
  }

  pendingApprovals = (sessionId: string) => this.source.pendingApprovals?.(sessionId) ?? Promise.resolve([]);

  async respondToConfirmation(turnId: string, callId: string, decision: "approve" | "deny") {
    await this.source.approve(turnId, callId, decision === "approve");
  }

  sessions = {
    list: async () => (await this.source.sessions()).map((s) => ({
      id: s.session_id, title: s.title ?? "Untitled", agentId: s.agent_id ?? undefined,
      updatedAt: s.last_activity_at ?? s.updated_at, preview: s.last_message_preview,
    })),
    /** Throws when the gateway can't load the session; the pane shows an ErrorState. */
    load: async (id: string): Promise<ChatSession> => {
      const rich = this.source.transcript?.(id);
      if (rich) return structuredClone(rich);
      const detail = await this.source.session(id);
      if (typeof detail.last_event_id === "number") this.advance(id, detail.last_event_id);
      return { id, title: detail.title ?? "Untitled", agentId: detail.agent_id ?? undefined, turns: messagesToTurns(detail.messages, this.agentName) };
    },
    save: async (session: ChatSession) => { localStorage.setItem(KEY(session.id), JSON.stringify(session)); },
    delete: async (id: string) => { localStorage.removeItem(KEY(id)); },
  };

  openExternal(url: string) { window.open(url, "_blank", "noopener"); }
  async copy(text: string) { if (!navigator.clipboard) throw new Error("Clipboard unavailable on this device"); await navigator.clipboard.writeText(text); }
  async listAgents(): Promise<ChatAgentRef[]> {
    return (await this.source.agents()).map((a) => ({ id: a.id, name: a.display_name ?? a.name }));
  }
}
