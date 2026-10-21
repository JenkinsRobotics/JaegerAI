import type { AgentActions, Section } from "./agentActions";
/* Typed port of jaeger_ai/interfaces/ide/gateway.js for the browser.
 * Same-origin only: the page is served by the Jaeger WebUI (or the Vite dev
 * proxy), which forwards /v1/* to the gateway and adds the caller token on the
 * server side. The browser never sees or sends a token. */
import { decodeSSE, type SSEFrame } from "./sse";
import type { JaegerSource, RequestSnapshot, PendingApproval, TurnReceipt , UploadedAttachment, ConnectAppsListing, ConnectedApp, ModelInventory, ScheduleControls, LibraryControls, ReactionSnapshot, SessionQueue } from "./source";
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
  sessionQueue: SessionQueue = {
    list: id => this.json(`/v1/sessions/${encodeURIComponent(id)}/queue`),
    enqueue: (id, text, request_id) => this.json(`/v1/sessions/${encodeURIComponent(id)}/queue`, { text, request_id }),
    update: (id, requestId, body) => this.json(`/v1/sessions/${encodeURIComponent(id)}/queue/${encodeURIComponent(requestId)}`, body, "PATCH"),
    reorder: (id, order) => this.json(`/v1/sessions/${encodeURIComponent(id)}/queue/reorder`, { order }),
    status: (id, requestId) => this.requestStatus(id, requestId),
  };
  messageReactions = {
    load: (id: string) => this.json<ReactionSnapshot>(`/v1/sessions/${encodeURIComponent(id)}/feedback`),
    save: (id: string, body: { request_id: string; role: "user" | "assistant"; emoji: string; active: boolean }) => this.json<ReactionSnapshot>(`/v1/sessions/${encodeURIComponent(id)}/feedback`, body),
  };
  library: LibraryControls = {
    list: () => this.json("/v1/library"),
    search: query => this.json(`/v1/library/search?q=${encodeURIComponent(query)}`),
    read: id => this.json(`/v1/library/documents/${encodeURIComponent(id)}`),
    versions: id => this.json(`/v1/library/documents/${encodeURIComponent(id)}/versions`),
    mutate: (action, id, body) => this.json(action === "create" ? "/v1/library/documents" : `/v1/library/documents/${encodeURIComponent(id)}/${action}`, body),
    operation: id => this.json(`/v1/control-operations/${encodeURIComponent(id)}`),
  };
  searchMessages(agentId: string, query: string, before?: string) { return this.json<import("./source").MessageSearchPage>(`/v1/agents/${encodeURIComponent(agentId)}/messages/search?q=${encodeURIComponent(query)}${before ? `&before=${encodeURIComponent(before)}` : ""}`); }
  readonly agentMemory: import('./source').AgentMemoryControls = {
    read: id => this.json(`/v1/agents/${encodeURIComponent(id)}/memory`),
    mutate: (id,body) => this.json(`/v1/agents/${encodeURIComponent(id)}/memory`,body),
    operation: id => this.json(`/v1/control-operations/${encodeURIComponent(id)}`),
  };
  readonly channelControls: NonNullable<import('./source').JaegerSource['channelControls']> = {
    mutate: (id,action,body) => this.json(`/v1/channels/${encodeURIComponent(id)}/${action}`,body),
    operation: id => this.json(`/v1/control-operations/${encodeURIComponent(id)}`),
  };
  channels() { return this.json<import("./source").ChannelSnapshot>("/v1/channels"); }
  diagnostics() { return this.json<import("./source").GatewayDiagnostics>("/v1/runtime/diagnostics"); }
  tools(query = "") { return this.json<import("./source").ToolInventory>(`/v1/runtime/tools?q=${encodeURIComponent(query)}`); }
  readonly notifications: import('./source').Notifications = {
    read: () => this.json('/v1/notifications'),
    save: body => this.json('/v1/notifications',body,'PATCH'),
    markRead: through => this.json('/v1/notifications',{read_through:through},'PATCH'),
  };
  readonly mcpControls: NonNullable<import('./source').JaegerSource['mcpControls']> = {
    mutate: (id,action,body) => this.json(`/v1/runtime/mcp/${encodeURIComponent(id)}/${action}`,body),
    operation: id => this.json(`/v1/control-operations/${encodeURIComponent(id)}`),
  };
  readonly sessionFiles: import('./source').SessionFiles = {
    list: sessionId => this.json(`/v1/sessions/${encodeURIComponent(sessionId)}/files`),
    read: (sessionId, id) => this.json(`/v1/sessions/${encodeURIComponent(sessionId)}/files/${encodeURIComponent(id)}`),
  };
  skillDetail(name: string, category: string) { return this.json<import('./source').SkillDetail>(`/v1/runtime/skills/detail?name=${encodeURIComponent(name)}&category=${encodeURIComponent(category)}`); }
  skills(query = "") { return this.json<{ skills: { name: string; category: string; description: string; lifecycle: string }[]; count: number }>(`/v1/runtime/skills?q=${encodeURIComponent(query)}`); }
  schedules: ScheduleControls = {
    list: () => this.json("/v1/schedules?include_deleted=1"),
    history: name => this.json(`/v1/schedules/history?job_id=${encodeURIComponent(name)}`),
    mutate: (action, body) => this.json(`/v1/schedules/${action}`, body),
    operation: id => this.json(`/v1/control-operations/${encodeURIComponent(id)}`),
  };
  modelSettings = {
    inventory: () => this.json<ModelInventory>("/api/runtime/models"),
    read: (id: string) => this.json<{ session_id: string; model?: string | null; provider?: string | null }>(`/v1/sessions/${encodeURIComponent(id)}?view=settings`),
    save: async (id: string, model: string | null) => { await this.json(`/v1/sessions/${encodeURIComponent(id)}`, { model }, "PATCH"); },
  };
  connectApps = {
    list: () => this.json<ConnectAppsListing>("/api/connect-apps"),
    state: (id: string) => this.json<{ id: string; state: ConnectedApp["state"] }>(`/api/connect-apps/${encodeURIComponent(id)}/state?refresh=1`),
    install: (id: string) => this.json<{ id?: string; state?: ConnectedApp["state"] }>(`/api/connect-apps/${encodeURIComponent(id)}/install`, { confirm: true }),
  };

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
  readonly workflows: import("./source").WorkflowControls = {
    list: () => this.json("/v1/workflows"),
    read: id => this.json(`/v1/workflows/${encodeURIComponent(id)}`),
    mutate: (action, id, body) => this.json(action === "create" ? "/v1/workflows" : `/v1/workflows/${encodeURIComponent(id)}/${action}`, body),
    operation: id => this.json(`/v1/control-operations/${encodeURIComponent(id)}`),
  };
  readonly agentKnowledge: import("./source").AgentKnowledgeControls = {
    read: id => this.json(`/v1/agents/${encodeURIComponent(id)}/knowledge`),
    save: (id, body) => this.json(`/v1/agents/${encodeURIComponent(id)}/knowledge`, body, "PATCH"),
  };
  readonly specialistControls: import("./source").SpecialistControls = {
    templates: () => this.json("/v1/agent-templates"),
    read: id => this.json(`/v1/agents/${encodeURIComponent(id)}/configuration`),
    save: (id, body) => this.json(`/v1/agents/${encodeURIComponent(id)}/configuration`, body, "PATCH"),
  };
  agentCreationStatus(operationId: string) { return this.json<{ receipt: { ok: boolean; agent?: Agent; error?: string } | null }>(`/v1/control-operations/${encodeURIComponent(operationId)}`); }
  createAgent(body: { template_id?: string; template_version?: number; operation_id?: string; name: string; display_name?: string; role?: string; metadata?: Record<string, unknown> }) {
    return this.json<Agent>("/v1/agents", { kind: "jaeger_native", role: "specialist", ...body });
  }
  readonly agentActions: AgentActions = {
    setPrimary: async (id, expectedId) => { await this.json("/v1/agents/primary", { agent_id: id, expected_agent_id: expectedId }); },
    markUnread: async (id) => { await this.json(`/v1/agents/${encodeURIComponent(id)}/seen`, { unread: true }); },
    savePins: async (ids, expectedIds) => { await this.json("/v1/agents/pins", { agent_ids: ids, expected_agent_ids: expectedIds }); },
    markRead: async (id, _messageId) => { await this.json(`/v1/agents/${encodeURIComponent(id)}/seen`, {}); },
    patchAgent: async (id, body) => { await this.json(`/v1/agents/${encodeURIComponent(id)}`, body, "PATCH"); },
    sections: async () => { const d = await this.json<{ sections?: Section[] } | Section[]>("/v1/sections"); return Array.isArray(d) ? d : d.sections ?? []; },
    createSection: (name) => this.json<Section>("/v1/sections", { name }),
    duplicate: (id, name) => this.json<Agent>(`/v1/agents/${encodeURIComponent(id)}/duplicate`, name ? { name } : {}),
    remove: async (id) => { await this.json(`/v1/agents/${encodeURIComponent(id)}`, { deleted: true }, "PATCH"); },
    template: (id) => this.json<unknown>(`/v1/agents/${encodeURIComponent(id)}/template`),
  };
  replyHandoff(handoffId: string, task: string, requestId: string) {
    return this.json<Handoff>(`/api/handoffs/${encodeURIComponent(handoffId)}/reply`, { task, request_id: requestId });
  }
  handoffExchange(handoffId: string) {
    return this.json<HandoffExchange>(`/api/handoffs/${encodeURIComponent(handoffId)}/messages`);
  }
  /** attachment_ids is always sent: left out, the gateway would attach every file the chat ever had. */
  send(sessionId: string, text: string, requestId: string, attachmentIds: string[] = []) {
    return this.json<TurnReceipt>(`/v1/sessions/${encodeURIComponent(sessionId)}/turns`, { text, request_id: requestId, attachment_ids: attachmentIds });
  }
  sessionControl(sessionId: string) {
    return this.json<{ latest_request?: { request_id: string; status: string } | null }>(`/v1/sessions/${encodeURIComponent(sessionId)}?view=control`);
  }
  requestStatus(sessionId: string, requestId: string) {
    return this.json<RequestSnapshot>(`/v1/sessions/${encodeURIComponent(sessionId)}/requests/${encodeURIComponent(requestId)}`);
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
  async pendingApprovals(sessionId: string): Promise<PendingApproval[]> {
    const data = await this.json<{ approvals: PendingApproval[] }>(`/v1/approvals?session_id=${encodeURIComponent(sessionId)}`);
    return data.approvals;
  }
  async approve(_sessionId: string, approvalId: string, approved: boolean) {
    await this.json(`/v1/approvals/${encodeURIComponent(approvalId)}`, { approved });
  }
  async tasks(): Promise<Task[]> {
    const data = await this.json<{ tasks?: Task[] } | Task[]>("/v1/tasks");
    return Array.isArray(data) ? data : data.tasks ?? [];
  }
  taskActions = {
    lookup: (sessionId: string, requestId: string) => this.json<{ session_id: string; request_id: string; tasks: Task[] }>(`/v1/task-submissions/${encodeURIComponent(requestId)}?session_id=${encodeURIComponent(sessionId)}`),
    create: (body: { session_id: string; goal: string; request_id: string; proposal: true }) => this.json<import("./source").TaskProposalReceipt>("/v1/tasks", body),
    edit: (id: string, goal: string, expected_updated_at: number) => this.json<Task>(`/v1/tasks/${encodeURIComponent(id)}`, { goal, expected_updated_at }, "PATCH"),
    approve: async (id: string, expected_updated_at: number) => { await this.json(`/v1/tasks/${encodeURIComponent(id)}/approve`, { expected_updated_at }); },
    cancel: async (id: string) => { await this.json(`/v1/tasks/${encodeURIComponent(id)}/cancel`, {}); },
  };
  agentHome(agentId: string) { return this.json<{ session_id: string; agent_id: string }>(`/v1/agents/${encodeURIComponent(agentId)}/home`); }
  async handoffs(query: { session_id?: string } = {}): Promise<Handoff[]> {
    const qs = query.session_id ? `?session_id=${encodeURIComponent(query.session_id)}` : "";
    const data = await this.json<{ handoffs?: Handoff[] } | Handoff[]>(`/api/handoffs${qs}`);
    return Array.isArray(data) ? data : data.handoffs ?? [];
  }

  async globalEvents(onEvent: (event: GatewayEvent) => void, signal: AbortSignal) {
    const response = await fetch(`${this.base}/v1/events/stream`, { headers: { Accept: "text/event-stream" }, credentials: "same-origin", signal });
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
