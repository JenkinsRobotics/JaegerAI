import type { AgentActions, Section } from "./agentActions";
/* Typed port of jaeger_ai/interfaces/ide/gateway.js for the browser.
 * Same-origin only: the page is served by the Jaeger WebUI (or the Vite dev
 * proxy), which forwards /v1/* to the gateway and adds the caller token on the
 * server side. The browser never sees or sends a token. */
import { decodeSSE, type SSEFrame } from "./sse";
import type { JaegerSource, TurnReceipt , UploadedAttachment } from "./source";
import type { Agent, AgentSummary, GatewayEvent, Handoff, HandoffExchange, SessionDetail, SessionRow, Task } from "./types";

export class GatewayError extends Error {
  constructor(message: string, readonly status: number, readonly body?: unknown) {
    super(message);
    this.name = "GatewayError";
  }
}

const TIMEOUT_MS = 15_000;

/** Wire envelope (server.py _sse_stream):
 *   id: <event_id> / event: <type> / data: {"event_id","session_id","event","timestamp","data":{request_id, turn_id, ...}}
 * Lift request_id / turn_id to the top and expose the inner object as `payload`. */
export function normalizeFrame(frame: SSEFrame): GatewayEvent {
  const envelope = (frame.data && typeof frame.data === "object" ? frame.data : {}) as Record<string, unknown>;
  const pick = (key: string) => (envelope[key] && typeof envelope[key] === "object" ? (envelope[key] as Record<string, unknown>) : undefined);
  const inner = pick("data") ?? pick("payload") ?? {};
  const id = frame.id ? Number(frame.id) : Number(envelope.event_id);
  return {
    event: String(frame.event ?? envelope.event ?? "message"),
    event_id: Number.isFinite(id) ? id : undefined,
    session_id: typeof envelope.session_id === "string" ? envelope.session_id : undefined,
    request_id: (inner.request_id ?? envelope.request_id) as string | undefined,
    turn_id: (inner.turn_id ?? envelope.turn_id) as string | undefined,
    created_at: typeof envelope.timestamp === "number" ? envelope.timestamp : undefined,
    payload: inner,
  };
}

export class GatewayClient implements JaegerSource {
  readonly kind = "live" as const;
  constructor(private readonly base = "") {}

  async json<T>(path: string, body?: unknown, method?: string, extraHeaders?: Record<string, string>): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const response = await fetch(`${this.base}${path}`, {
        method: method ?? (body === undefined ? "GET" : "POST"),
        headers: { ...(body === undefined ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json" }), ...extraHeaders },
        body: body === undefined ? undefined : JSON.stringify(body),
        credentials: "same-origin",
        signal: controller.signal,
      });
      const text = await response.text();
      let data: unknown = text;
      try { data = text ? JSON.parse(text) : {}; } catch { /* non-JSON body */ }
      if (!response.ok) {
        const message = (data as { error?: string })?.error ?? `${response.status} ${response.statusText}`;
        throw new GatewayError(String(message), response.status, data);
      }
      return data as T;
    } finally {
      clearTimeout(timer);
    }
  }

  async agents(): Promise<Agent[]> {
    const data = await this.json<{ agents?: Agent[] } | Agent[]>("/v1/agents");
    return Array.isArray(data) ? data : data.agents ?? [];
  }
  async agentsSummary(): Promise<AgentSummary[]> {
    return (await this.json<{ agents?: AgentSummary[] }>("/v1/agents/summary")).agents ?? [];
  }
  async sessions(query: { agent_id?: string } = {}): Promise<SessionRow[]> {
    const qs = query.agent_id ? `?agent_id=${encodeURIComponent(query.agent_id)}` : "";
    return (await this.json<{ sessions?: SessionRow[] }>(`/v1/sessions${qs}`)).sessions ?? [];
  }
  session(id: string) { return this.json<SessionDetail>(`/v1/sessions/${encodeURIComponent(id)}`); }
  createSession(body: { agent_id?: string; title?: string }) {
    return this.json<SessionRow>("/v1/sessions", { session_id: crypto.randomUUID(), source: "webui", title: body.title ?? "New chat", ...body });
  }
  async updateSession(id: string, body: { title?: string; archived?: boolean }) {
    await this.json(`/v1/sessions/${encodeURIComponent(id)}`, body, "PATCH");
  }
  createAgent(body: { name: string; display_name?: string; role?: string; metadata?: Record<string, unknown> }) {
    return this.json<Agent>("/v1/agents", { kind: "jaeger_native", role: "specialist", ...body });
  }
  readonly agentActions: AgentActions = {
    markRead: async (id, messageId) => { await this.json(`/v1/agents/${encodeURIComponent(id)}/read`, { message_id: messageId }); },
    patchAgent: async (id, body) => { await this.json(`/v1/agents/${encodeURIComponent(id)}`, body, "PATCH"); },
    sections: async () => { const d = await this.json<{ sections?: Section[] } | Section[]>("/v1/sections"); return Array.isArray(d) ? d : d.sections ?? []; },
    createSection: (name) => this.json<Section>("/v1/sections", { name }),
    duplicate: (id, name) => this.json<Agent>(`/v1/agents/${encodeURIComponent(id)}/duplicate`, name ? { name } : {}),
    remove: async (id) => { await this.json(`/v1/agents/${encodeURIComponent(id)}`, undefined, "DELETE"); },
    template: (id) => this.json<unknown>(`/v1/agents/${encodeURIComponent(id)}/template`),
  };
  handoffExchange(handoffId: string) {
    return this.json<HandoffExchange>(`/api/handoffs/${encodeURIComponent(handoffId)}/messages`);
  }
  /** attachment_ids is always sent: left out, the gateway would attach every file the chat ever had. */
  send(sessionId: string, text: string, requestId: string, attachmentIds: string[] = []) {
    return this.json<TurnReceipt>(`/v1/sessions/${encodeURIComponent(sessionId)}/turns`, { text, request_id: requestId, attachment_ids: attachmentIds });
  }
  addAttachment(sessionId: string, body: { path: string; filename?: string; mime_type?: string }) {
    return this.json<{ attachment_id: string }>(`/v1/sessions/${encodeURIComponent(sessionId)}/attachments`, body);
  }
  /** Bytes, not a path: JSON {name, mime, data_base64} (the route also takes multipart 'file' + 'name'). */
  /** idempotencyKey: one per file, so a retried upload replays the same attachment instead of staging a second. */
  uploadAttachment(sessionId: string, body: { name: string; mime: string; data_base64: string }, idempotencyKey?: string) {
    return this.json<UploadedAttachment>(`/v1/sessions/${encodeURIComponent(sessionId)}/attachments/upload`, body, undefined,
      idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined);
  }
  async cancel(sessionId: string, requestId?: string) {
    await this.json(`/v1/sessions/${encodeURIComponent(sessionId)}/cancel`, requestId ? { request_id: requestId } : {});
  }
  async approve(_sessionId: string, approvalId: string, approved: boolean) {
    await this.json(`/v1/approvals/${encodeURIComponent(approvalId)}`, { approved });
  }
  async tasks(): Promise<Task[]> {
    const data = await this.json<{ tasks?: Task[] } | Task[]>("/v1/tasks");
    return Array.isArray(data) ? data : data.tasks ?? [];
  }
  async handoffs(query: { session_id?: string } = {}): Promise<Handoff[]> {
    const qs = query.session_id ? `?session_id=${encodeURIComponent(query.session_id)}` : "";
    const data = await this.json<{ handoffs?: Handoff[] } | Handoff[]>(`/api/handoffs${qs}`);
    return Array.isArray(data) ? data : data.handoffs ?? [];
  }

  async globalEvents(onEvent: (event: GatewayEvent) => void, signal: AbortSignal) {
    const response = await fetch(`${this.base}/v1/events`, { headers: { Accept: "text/event-stream" }, credentials: "same-origin", signal });
    if (!response.ok || !response.body) throw new GatewayError(`events ${response.status}`, response.status, undefined);
    for await (const frame of decodeSSE(response.body, signal)) onEvent(normalizeFrame(frame));
  }

  async stream(sessionId: string, cursor: number | undefined, onEvent: (event: GatewayEvent) => void, signal: AbortSignal) {
    const qs = cursor ? `?last_event_id=${cursor}` : "";
    const response = await fetch(`${this.base}/v1/sessions/${encodeURIComponent(sessionId)}/stream${qs}`, {
      headers: { Accept: "text/event-stream" }, credentials: "same-origin", signal,
    });
    if (!response.ok || !response.body) {
      let body: unknown;
      try { body = await response.json(); } catch { /* not JSON */ }
      throw new GatewayError((body as { error?: string })?.error ?? `stream ${response.status}`, response.status, body);
    }
    for await (const frame of decodeSSE(response.body, signal)) onEvent(normalizeFrame(frame));
  }
}
