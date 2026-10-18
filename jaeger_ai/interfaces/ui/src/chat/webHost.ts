/* WebHost: ChatHost for the browser. Data comes from a JaegerSource (live =
 * same-origin /v1 and /api fetches; mock = dev-only sample data). Failures
 * surface to the caller; there is no silent fallback. */
import type { JaegerSource } from "../api/source";
import type { PersistedPart, SessionMessage } from "../api/types";
import { followTurn } from "./followTurn";
import type { ChatAgentRef, ChatHost, ChatPart, ChatSession, HostKind, StartTurnRequest, TurnHandle, TurnState } from "./host";
import type { HostAttachment, HostCapabilities } from "./hostH8";

const KEY = (id: string) => `jaeger.ui.session.${id}`;

function persistedToPart(p: PersistedPart, agentName: (id: string) => string): ChatPart | null {
  switch (p.type) {
    case "text": return p.text ? { kind: "markdownContent", text: p.text } : null;
    case "reasoning": return { kind: "thinking", text: p.text ?? "", durationMs: p.duration_ms };
    case "tool": return {
      kind: "toolInvocation", callId: String(p.call_id ?? ""), toolName: String(p.tool ?? "tool"), input: p.input ?? null,
      state: p.status === "done" ? "completed" : p.status === "error" ? "cancelled" : "executing", output: p.output,
    };
    case "handoff": {
      const agentId = String(p.agent_id ?? "");
      return { kind: "handoff", handoffId: String(p.handoff_id ?? ""), agentId, agentName: p.agent_name || agentName(agentId), count: 1, direction: p.direction };
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
      turns.push({ turnId: m.request_id ?? `t${turns.length}`, message: m.content ?? "", parts: [], state: "complete", createdAt: epochMs(m) });
    } else if (m.role === "assistant") {
      // A reply with no user turn before it (proactive note, relayed report) still shows.
      if (!turns.length) turns.push({ turnId: `t${turns.length}`, message: "", parts: [], state: "complete", createdAt: epochMs(m) });
      const parts = m.parts?.length
        ? m.parts.map((p) => persistedToPart(p, agentName)).filter((p): p is ChatPart => p !== null)
        : [{ kind: "markdownContent" as const, text: m.content ?? "" }];
      turns[turns.length - 1].parts.push(...parts);
    }
  }
  return turns;
}

const message = (error: unknown) => String((error as Error)?.message ?? error);

export class WebHost implements ChatHost {
  readonly kind: HostKind = "web";
  capabilities: HostCapabilities = { voice: false };
  /** Set by the app: a handoff marker opens the specialist's side of it. */
  openHandoff?: (handoffId: string) => void;
  /** Set by the app: the header pill opens the agent's details panel. */
  openDetails?: (agentId: string) => void;
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
  private async registerAttachments(sessionId: string, files: HostAttachment[], onPart: (part: ChatPart) => void): Promise<string[]> {
    const ids: string[] = [];
    const skipped: string[] = [];
    for (const file of files) {
      if (!file.path) { skipped.push(`${file.name} (no file path from this window)`); continue; }
      try {
        const row = await this.source.addAttachment(sessionId, { path: file.path, filename: file.name, mime_type: file.mimeType });
        ids.push(row.attachment_id);
      } catch (error) {
        skipped.push(`${file.name} (${message(error)})`);
      }
    }
    if (skipped.length) onPart({ kind: "warning", message: `Not sent: ${skipped.join(", ")}. The rest of your message went through.` });
    return ids;
  }
  async listModels() { return []; }

  startTurn(request: StartTurnRequest, onPart: (part: ChatPart) => void): TurnHandle {
    const controller = new AbortController();
    const requestId = request.turnId;
    let admitted = false;
    const done = (async (): Promise<{ state: TurnState }> => {
      // The gateway attaches workspace files by path. Host-picked files (H8 `path`) are registered first;
      // pasted or dropped ones have no path, so they're named in a warning instead of silently dropped.
      const attachmentIds = await this.registerAttachments(request.sessionId, request.attachments ?? [], onPart);
      let receipt;
      try {
        receipt = await this.source.send(request.sessionId, request.message, requestId, attachmentIds);
      } catch (error) {
        onPart({ kind: "error", message: message(error) });
        return { state: "failed" };
      }
      admitted = true;
      if (controller.signal.aborted) { void this.source.cancel(request.sessionId, receipt.request_id); return { state: "cancelled" }; }
      const start = typeof receipt.start_event_id === "number" ? receipt.start_event_id - 1 : 0;
      return followTurn({
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
    })();
    return {
      cancel: () => {
        if (admitted) void this.source.cancel(request.sessionId, requestId);
        controller.abort();
      },
      done,
    };
  }

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
  async copy(text: string) { await navigator.clipboard?.writeText(text); }
  async listAgents(): Promise<ChatAgentRef[]> {
    return (await this.source.agents()).map((a) => ({ id: a.id, name: a.display_name ?? a.name }));
  }
}
