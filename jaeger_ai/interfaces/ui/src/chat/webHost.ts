/* WebHost: ChatHost for the browser. Data comes from a JaegerSource (live =
 * same-origin /v1 and /api fetches; mock = sample data). Sessions cache in
 * localStorage. */
import { MOCK_TRANSCRIPTS } from "../api/mock";
import type { JaegerSource } from "../api/source";
import type { SessionMessage } from "../api/types";
import { mapEvent } from "./eventMap";
import type { ChatAgentRef, ChatHost, ChatPart, ChatSession, HostKind, StartTurnRequest, TurnHandle, TurnState } from "./host";

const KEY = (id: string) => `jaeger.ui.session.${id}`;

function messagesToTurns(messages: SessionMessage[] = []): ChatSession["turns"] {
  const turns: ChatSession["turns"] = [];
  for (const m of messages) {
    if (m.role === "user") turns.push({ turnId: m.request_id ?? `t${turns.length}`, message: m.content ?? "", parts: [], state: "complete" });
    else if (m.role === "assistant" && turns.length) turns[turns.length - 1].parts.push({ kind: "markdownContent", text: m.content ?? "" });
  }
  return turns;
}

export class WebHost implements ChatHost {
  readonly kind: HostKind = "web";
  capabilities = { voice: false };
  /** Set by the app: opens the exchange panel for a handoff marker. */
  openHandoff?: (handoffId: string) => void;
  private agentNames = new Map<string, string>();

  constructor(protected readonly source: JaegerSource) {}

  setAgentNames(names: Map<string, string>) { this.agentNames = names; }
  private agentName = (id: string) => this.agentNames.get(id) ?? id;

  async getConfig() { return { defaultMode: "agent" }; }
  async listModels() { return []; }

  startTurn(request: StartTurnRequest, onPart: (part: ChatPart) => void): TurnHandle {
    const controller = new AbortController();
    let requestId: string | undefined;
    let finish: (value: { state: TurnState }) => void = () => {};
    const done = new Promise<{ state: TurnState }>((resolve) => { finish = resolve; });
    const settle = (state: TurnState) => { controller.abort(); finish({ state }); };
    void this.source
      .stream(request.sessionId, undefined, (event) => {
        if (requestId && event.request_id && event.request_id !== requestId) return;
        const mapped = mapEvent(event, this.agentName);
        mapped?.parts.forEach(onPart);
        if (mapped?.state) settle(mapped.state);
      }, controller.signal)
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        onPart({ kind: "error", message: String((error as Error)?.message ?? error) });
        settle("failed");
      });
    this.source.send(request.sessionId, request.message).then(
      (reply) => { requestId = reply.request_id; },
      (error: unknown) => { onPart({ kind: "error", message: String((error as Error)?.message ?? error) }); settle("failed"); },
    );
    return {
      cancel: () => { void this.source.cancel(request.sessionId, requestId); },
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
    load: async (id: string): Promise<ChatSession> => {
      if (this.source.kind === "mock" && MOCK_TRANSCRIPTS[id]) return structuredClone(MOCK_TRANSCRIPTS[id]);
      try {
        const detail = await this.source.session(id);
        return { id, title: detail.title ?? "Untitled", agentId: detail.agent_id ?? undefined, turns: messagesToTurns(detail.messages) };
      } catch {
        const cached = localStorage.getItem(KEY(id));
        if (cached) return JSON.parse(cached) as ChatSession;
        return { id, title: "New chat", turns: [] };
      }
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
