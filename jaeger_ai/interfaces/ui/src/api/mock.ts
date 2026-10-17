/* Typed mock adapter. DEV ONLY: loaded through a dynamic import that
 * production builds drop (see api/index.ts). Sample roster, previews,
 * tasks, and transcripts with every ChatPart kind and each handoff marker
 * shape. send() replays a scripted gateway event sequence over stream(). */
import type { ChatSession } from "../chat/host";
import type { JaegerSource } from "./source";
import type { Agent, AgentSummary, GatewayEvent, Handoff, SessionDetail, SessionRow, Task } from "./types";

const now = () => Date.now() / 1000;
const ago = (minutes: number) => now() - minutes * 60;

export const MOCK_AGENTS: Agent[] = [
  { id: "native:jaeger", name: "jaeger", display_name: "Jaeger", role: "lead", kind: "native", runner: "native" },
  { id: "agent:gateway-webui", name: "gateway-webui", display_name: "Jaeger Gateway & WebUI", role: "specialist", kind: "native", runner: "delegate:claude-code" },
  { id: "agent:mac-app", name: "mac-app", display_name: "Mac App", role: "specialist", kind: "native", runner: "delegate:codex" },
  { id: "agent:ide-chat", name: "ide-chat", display_name: "IDE Chat", role: "specialist", kind: "native", runner: "delegate:claude-code" },
  { id: "agent:agents-view", name: "agents-view", display_name: "Agents View", role: "specialist", kind: "native", runner: "native" },
  { id: "agent:architect-notes", name: "architect-notes", display_name: "Architect & Notes", role: "specialist", kind: "native", runner: "delegate:grok-cli" },
  { id: "native:gateway", name: "gateway", role: "native", kind: "native", metadata: { internal: true } },
];

const summary = (id: string, minutes: number, preview: string, unseen: boolean, status = "idle"): AgentSummary => ({
  id, display_name: MOCK_AGENTS.find((a) => a.id === id)?.display_name, role: id === "native:jaeger" ? "lead" : "specialist",
  status, last_activity_at: ago(minutes), last_preview: preview, last_source: "handoff", session_id: `s-${id}`, unseen,
});

export const MOCK_SUMMARY: AgentSummary[] = [
  summary("native:jaeger", 1, "Split the UI rebuild across four specialists.", false, "working"),
  summary("agent:agents-view", 2, "Sidebar, markers and shell are rendering in mock mode.", true, "working"),
  summary("agent:ide-chat", 6, "ChatHost interface frozen; mount(el, host, opts) ⇒ dispose.", true, "working"),
  summary("agent:gateway-webui", 14, "Shipped /v1/agents/summary and the global events stream.", false),
  summary("agent:mac-app", 31, "WKWebView shell loads 127.0.0.1:8790/?host=macos.", false, "waiting_approval"),
  summary("agent:architect-notes", 95, "Reuse audit: extend /v1/tasks instead of a new status route.", false),
];

export const MOCK_TASKS: Task[] = [
  { task_id: "t1", goal: "Build the new main screen (sidebar + chat)", state: "running", agent_id: "agent:agents-view", runner: "native", eta: "3:30 PM", updated_at: ago(2) },
  { task_id: "t2", goal: "Port the VS Code chat widget into jaeger-chat-ui", state: "running", agent_id: "agent:ide-chat", runner: "delegate:claude-code", eta: "5:00 PM", updated_at: ago(6) },
  { task_id: "t3", goal: "Extend /v1/tasks with agent_id, eta, runner", state: "done", agent_id: "agent:gateway-webui", runner: "delegate:claude-code", updated_at: ago(14) },
  { task_id: "t4", goal: "Serve interfaces/ui/dist from the WebUI at /", state: "queued", agent_id: "agent:gateway-webui", runner: "delegate:claude-code", updated_at: ago(20) },
  { task_id: "t5", goal: "Sign and notarize the Mac shell", state: "needs_owner", agent_id: "agent:mac-app", runner: "delegate:codex", updated_at: ago(31) },
  { task_id: "t6", goal: "Decide: wire or archive session_titler.py", state: "blocked", agent_id: "agent:architect-notes", runner: "delegate:grok-cli", updated_at: ago(95) },
];

const name = (id: string) => MOCK_AGENTS.find((a) => a.id === id)?.display_name ?? id;
const ref = (id: string) => ({ id, name: name(id) });

export const MOCK_TRANSCRIPTS: Record<string, ChatSession> = {
  "s-native:jaeger": {
    id: "s-native:jaeger", title: "Jaeger UI rebuild", agentId: "native:jaeger", updatedAt: ago(1),
    turns: [
      {
        turnId: "m1", state: "complete",
        message: "Where are we on the UI rebuild? I want the new main screen today.",
        parts: [
          { kind: "thinking", text: "Four tracks: shell + sidebar, the shared chat widget, the gateway endpoints, and the Mac shell.", durationMs: 12_000 },
          { kind: "markdownContent", text: "On it. I split the work so nothing blocks the 3:30 PM screenshot." },
          { kind: "handoff", handoffId: "h1", agentId: "agent:agents-view", agentName: name("agent:agents-view"), count: 1, direction: "to", agents: [ref("agent:agents-view"), ref("agent:ide-chat")] },
          { kind: "handoff", handoffId: "h2", agentId: "agent:gateway-webui", agentName: name("agent:gateway-webui"), count: 4, direction: "to" },
          { kind: "handoff", handoffId: "h3", agentId: "agent:mac-app", agentName: name("agent:mac-app"), count: 1, direction: "from" },
          { kind: "markdownContent", text: "Here's where things stand:\n\n- **Agents View** is building the sidebar, shell and markers in `interfaces/ui`.\n- **IDE Chat** owns the shared chat renderer. `ChatHost` is frozen.\n- **Gateway & WebUI** shipped `/v1/agents/summary` and the global stream.\n- **Mac App** has the WKWebView shell loading `?host=macos`." },
        ],
      },
      {
        turnId: "m2", state: "needs_input",
        message: "Run the build on the worktree and commit if it's green.",
        parts: [
          { kind: "progress", message: "Checking the worktree" },
          { kind: "toolInvocation", callId: "c1", toolName: "npm run build", input: { cwd: "jaeger_ai/interfaces/ui" }, state: "completed", output: "✓ built in 1.9s" },
          { kind: "markdownContent", text: "Build is green: theme check, `tsc` and `vite build` all pass." },
          { kind: "toolInvocation", callId: "c2", toolName: "git commit", input: { pathspec: "jaeger_ai/interfaces/ui" }, state: "waitingForConfirmation" },
          { kind: "confirmation", callId: "c2", title: "Run git commit?", message: "Commit 14 files under jaeger_ai/interfaces/ui on feat/ui-rebuild." },
          { kind: "warning", message: "Sample warning (dev mock data): the build log has 2 deprecation notices." },
        ],
      },
    ],
  },
};

const turnScript = (sessionId: string, text: string): Array<[number, GatewayEvent]> => [
  [150, { event: "turn.start", session_id: sessionId }],
  [250, { event: "turn.reasoning", payload: { text: "Reading the request.", duration_ms: 1_000 } }],
  [200, { event: "turn.progress", payload: { message: "Looking at the roster" } }],
  ...`Got it: "${text.slice(0, 60)}". This is the mock adapter, so no agent actually ran.`.split(/(?<= )/).map((delta) => [45, { event: "turn.delta", payload: { delta, channel: "provisional" } }] as [number, GatewayEvent]),
  [150, { event: "turn.finish", payload: {} }],
];

export class MockSource implements JaegerSource {
  readonly kind = "mock" as const;
  private listeners = new Map<string, Set<(event: GatewayEvent) => void>>();
  /** Per-session event log so stream(cursor) replays like the gateway does. */
  private log = new Map<string, GatewayEvent[]>();
  private eventId = 1000;
  private timers: ReturnType<typeof setTimeout>[] = [];

  async agents() { return MOCK_AGENTS; }
  async agentsSummary() { return MOCK_SUMMARY; }
  async sessions(query: { agent_id?: string } = {}): Promise<SessionRow[]> {
    return MOCK_SUMMARY.filter((s) => !query.agent_id || s.id === query.agent_id).map((s) => ({
      session_id: s.session_id!, agent_id: s.id, title: MOCK_TRANSCRIPTS[s.session_id!]?.title ?? s.display_name,
      last_message_preview: s.last_preview, last_activity_at: s.last_activity_at ?? undefined, updated_at: s.last_activity_at ?? undefined,
    }));
  }
  async session(id: string): Promise<SessionDetail> {
    return { session_id: id, title: MOCK_TRANSCRIPTS[id]?.title ?? name(id.replace(/^s-/, "")), messages: [], last_event_id: this.eventId };
  }
  transcript(id: string) { return MOCK_TRANSCRIPTS[id]; }
  async createSession(body: { agent_id?: string; title?: string }): Promise<SessionRow> {
    return { session_id: `s-new-${Date.now()}`, agent_id: body.agent_id, title: body.title ?? "New chat", created_at: now() };
  }
  async send(sessionId: string, text: string, requestId: string) {
    const start = this.eventId + 1;
    let delay = 0;
    turnScript(sessionId, text).forEach(([wait, event], index) => {
      if (index === 0) { this.emit(sessionId, { ...event, request_id: requestId }); return; }
      delay += wait;
      this.timers.push(setTimeout(() => this.emit(sessionId, { ...event, request_id: requestId }), delay));
    });
    return { request_id: requestId, start_event_id: start, status: "running" };
  }
  async cancel(sessionId: string, requestId?: string) {
    this.timers.forEach(clearTimeout);
    this.timers = [];
    this.emit(sessionId, { event: "turn.cancelled", request_id: requestId, payload: {} });
  }
  async approve() { /* mock: accepted */ }
  async tasks() { return MOCK_TASKS; }
  async handoffs(): Promise<Handoff[]> {
    return [{ id: "h2", from_agent_id: "native:jaeger", to_agent_id: "agent:gateway-webui", status: "completed", task: "Ship /v1/agents/summary", updated_at: ago(14) }];
  }
  stream(sessionId: string, cursor: number | undefined, onEvent: (event: GatewayEvent) => void, signal: AbortSignal): Promise<void> {
    for (const event of this.log.get(sessionId) ?? []) if ((event.event_id ?? 0) > (cursor ?? 0)) onEvent(event);
    const set = this.listeners.get(sessionId) ?? new Set();
    this.listeners.set(sessionId, set);
    set.add(onEvent);
    return new Promise((resolve) => signal.addEventListener("abort", () => { set.delete(onEvent); resolve(); }, { once: true }));
  }
  private emit(sessionId: string, event: GatewayEvent) {
    this.eventId += 1;
    const framed = { ...event, event_id: this.eventId };
    const log = this.log.get(sessionId) ?? [];
    log.push(framed);
    this.log.set(sessionId, log.slice(-500));
    this.listeners.get(sessionId)?.forEach((cb) => cb(framed));
  }
}
