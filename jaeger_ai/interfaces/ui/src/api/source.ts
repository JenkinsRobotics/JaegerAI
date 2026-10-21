import type { HomeOptions, HomeSessions } from "../chat/homeSession";
import type { ChatSession } from "../chat/host";
import type { Agent, AgentSummary, GatewayEvent, Handoff, HandoffExchange, SessionDetail, SessionRow, Task } from "./types";

/** Everything the screen needs from Jaeger. The live adapter calls the
 * gateway through same-origin paths; the mock adapter replays sample data. */
/** 201 from the bytes upload route. */
export interface SessionFile { attachment_id: string; name: string; mime: string; size: number; sha256: string; readable: boolean; unavailable_reason?: string }
export interface SessionFiles {
  list(sessionId: string): Promise<{ session_id: string; files: SessionFile[]; max_bytes: number }>;
  read(sessionId: string, attachmentId: string): Promise<{ session_id: string; attachment_id: string; name: string; mime: string; size: number; sha256: string; data_base64: string }>;
}
export interface UploadedAttachment { attachment_id: string; name: string; mime: string; size: number; sha256: string }

import type { AgentActions } from "./agentActions";

export interface PendingApproval {
  approval_id: string; session_id?: string; kind: string; prompt: string;
  task?: string; status: string;
}

export interface RequestSnapshot {
  request_id: string; session_id: string; turn_id?: string; status: string; input_text?: string;
  result?: { output?: string; error?: string; summary?: string; [key: string]: unknown };
}
export interface ConnectedApp {
  id: string; name: string; description?: string; category?: string; status: string; actions: string[];
  state: { value: string; detail?: string; version?: string; checked_at?: number };
}
export interface ConnectAppsListing { apps: ConnectedApp[]; categories: { id: string; label: string }[]; connected_count: number }
export interface ModelInventory {
  active?: { provider: string; model: string };
  providers: { id: string; display_name: string; reachable: boolean; configured: boolean; availability?:'not_probed'|'not_configured'|'unknown';configuration_observed?:boolean;reason?: string; models: { id: string; available?: boolean; usable_for_react?: boolean }[] }[];
}
export interface ModelChoiceSnapshot {session_id:string;model?:string|null;provider?:string|null;model_choice_revision?:number;atomic_model_operations?:boolean}
export interface ModelChoiceReceipt extends ControlResult {domain:string;session_id:string}
export interface ModelChoiceIntent {operation_id:string;model:string|null;expected_model_revision:number}
export interface ModelSettings {
  inventory(): Promise<ModelInventory>;
  read(sessionId: string): Promise<ModelChoiceSnapshot>;
  saveVersioned?(sessionId:string,body:ModelChoiceIntent):Promise<ModelChoiceReceipt>;
  cancelPending?(sessionId:string,body:ModelChoiceIntent):Promise<ModelChoiceReceipt>;
  operation?(id:string):Promise<{receipt:ModelChoiceReceipt|null}>;
  save(sessionId: string, model: string | null): Promise<void>;
}
export interface ScheduleJob { id: string; name: string; prompt: string; cron: string; enabled: boolean; state: string; next_fire_at?: string; timezone?: string | null; timezone_policy?: string; config_revision?: number }
export type ScheduleAction = "create" | "update" | "pause" | "resume" | "delete" | "restore" | "run";
export interface ControlResult { execution_unknown?: boolean; ok: boolean; operation_id: string; result?: unknown; error?: string; http_status?: number }
export interface ScheduleControls {
  list(): Promise<{ jobs: ScheduleJob[]; scheduler: string }>;
  history(name: string): Promise<{ tasks: Task[]; requests: RequestSnapshot[] }>;
  mutate(action: ScheduleAction, body: { operation_id: string; job_id?: string; name?: string; prompt?: string; schedule?: string; timezone?: string; expected_revision?: number }): Promise<ControlResult>;
  operation(id: string): Promise<{ receipt: ControlResult | null }>;
}
export interface LibraryDocument { id: string; title: string; content: string; digest: string; revision?: number; archived?: boolean; editable?: boolean; provenance?:Record<string,unknown> }
export interface LibraryControls {
  list(): Promise<{ limits?: { document_bytes: number }; documents: Omit<LibraryDocument, "content">[]; collections: { id: string; label: string; kind: string }[] }>;
  search(query: string): Promise<{ results: { id: string; title: string; snippet: string }[] }>;
  read(id: string): Promise<LibraryDocument>;
  versions(id: string): Promise<{ versions: { revision: number; title: string; created_at: number }[] }>;
  mutate(action: "create" | "save" | "archive" | "restore" | "version", id: string, body: Record<string, unknown>): Promise<ControlResult & { document?: { id: string; revision: number; digest: string; archived: boolean } }>;
  operation(id: string): Promise<{ receipt: (ControlResult & { document?: { id: string } }) | null }>;
}

export interface ReactionSnapshot { reactions: Record<string, string[]>; event_id: number; allowed_emojis: string[] }
export interface QueuedRequest extends RequestSnapshot { input_text: string; queue_position?: number; updated_at: number }
export interface SessionQueue {
  list(sessionId: string): Promise<{ session_id: string; items: QueuedRequest[] }>;
  enqueue(sessionId: string, text: string, requestId: string): Promise<{ session_id: string; request_id: string; status: string }>;
  update(sessionId: string, requestId: string, body: { text?: string; status?: "queued" | "paused"; expected_updated_at: number }): Promise<unknown>;
  reorder(sessionId: string, order: string[]): Promise<unknown>;
  status(sessionId: string, requestId: string): Promise<RequestSnapshot>;
}
export interface SpecialistSettings { specialty: string; summary: string; instructions: string }
export interface SpecialistConfiguration extends SpecialistSettings { agent_id: string; revision: number; editable: boolean; template?: { id: string; version: number } }
export interface AgentTemplate extends SpecialistSettings { id: string; version: number; name: string; tools_granted: false }
export interface SpecialistControls {
  templates(): Promise<{ templates: AgentTemplate[] }>;
  read(id: string): Promise<SpecialistConfiguration>;
  save(id: string, body: { expected_revision: number; settings: SpecialistSettings }): Promise<SpecialistConfiguration>;
}
export interface SkillDetail {
  name: string; category: string; description: string; origin: string; lifecycle: string; skill_class: string;
  platforms: string[]; requires_tools: string[]; optional_tools: string[]; requires_toolsets: string[];
  requires_plugins: string[]; aliases: string[]; tags: string[]; auto_activate: boolean; tier: string;
  availability: string; origin_verified: false; execution_authorized: false; scope: string;
}
export interface NotificationPreferences { revision:number;enabled:boolean;muted_agent_ids:string[];read_through:number }
export interface Notifications {
  read(options?:{before?:number;category?:string}):Promise<{preferences:NotificationPreferences;notifications:{event_id:number;session_id:string;agent_id?:string;title:string;status?:string;timestamp:number;unread:boolean}[];privacy:string;enabled:boolean;observed_through?:number;next_before?:number|null;category?:string;categories?:{id:string;label:string}[]}>;
  save(body:{expected_revision:number;enabled:boolean;muted_agent_ids:string[]}):Promise<{preferences:NotificationPreferences}>;
  markRead(through:number):Promise<{preferences:NotificationPreferences}>;
}
export interface ResourceCatalog { server_id:string;resources:{id:string;title:string;description:string;mime:string}[];next_page:string|null;truncated:boolean;availability:string;no_grants:true }
export interface ResourceSnapshot { id:string;title:string;server_id:string;resource_id:string;text:string;digest:string;redacted:boolean;observed_at:number;source:string;authority:string }
export interface ResourceReceipt extends ControlResult { result?:{catalog?:ResourceCatalog;snapshot?:Omit<ResourceSnapshot,'text'>;volatile_content?:boolean;document?:{id:string;revision:number;digest:string;provenance:Record<string,unknown>}} }
export interface MCPResources {
  mutate(serverId:string,action:'list'|'read'|'import',body:Record<string,unknown>):Promise<ResourceReceipt>;
  snapshot(serverId:string,id:string):Promise<ResourceSnapshot>;
  operation(id:string):Promise<{receipt:ResourceReceipt|null}>;
}
export interface ToolInventory {
  tools: { name: string; description: string; toolset: string; source: string; server: string | null; side_effect: string; permission_tier: string; beta: boolean; dangerous: boolean; availability: string }[];
  count: number; servers: { id?: string; name: string; state: string; tool_count: number; active_calls?: number; actions?: string[]; resources_advertised?:boolean }[];
  mcp_initialized: boolean; scope: string; execution_authorized: false;
}
export interface InstalledPlugin {slot_id?:string;startup_revision?:number;startup_known?:boolean;startup_policy?:'legacy'|'disabled'|'enabled_revision'|'revision_unapproved'|'unknown';startup_editable?:boolean;startup_approvable?:boolean;startup_revision_id?:string;restart_required?:boolean;distribution_state?:'current'|'replaced'|'removed';activation_blocked_by_loaded_revision?:boolean;related_revision_ids?:string[];id:string;name:string;package:string;version:string;state:string;active_hooks:number;hook_count:number;tool_count:number;command_count:number;actions:('pause_hooks'|'resume_hooks')[];provenance:string}
export interface PackagePlan {package:string;version:string|null;installed_version:string|null;sha256?:string;attachment_id?:string;expected_fingerprint:string;policy_revision:number;entries:{name:string;value:string;slot_id:string}[];requires:string[];restart_required:boolean;activation_performed:false;provenance:string}
export type PackageReview={action:'install';session_id:string;attachment_id?:string;upload_key?:string}|{action:'remove';package:string}|{action:'restore';restore_from:string};
export type PackageCommand={operation_id:string;expected_fingerprint:string;expected_policy_revision:number}&({action:'install';session_id:string;attachment_id:string;sha256:string}|{action:'remove';package:string}|{action:'restore';restore_from:string});
export interface PluginPackages {
 list(before?:string):Promise<{environment:string;next_before?:string|null;operations:{operation_id:string;package:string;version:string|null;action:string;phase:string;backup_available:boolean}[];supported:string;activation_performed:false}>;
 preview(body:PackageReview):Promise<PackagePlan>;
 change(body:PackageCommand):Promise<ControlResult>;
 operation(id:string):Promise<{receipt:ControlResult|null;pending?:{error?:string;phase?:string}}>;
}
export interface PluginControls {
  packages?:PluginPackages;
  startup?(id:string,body:{operation_id:string;expected_revision:number;enabled:boolean}):Promise<ControlResult>;
  list():Promise<{plugins:InstalledPlugin[];scope:string;activation_performed:false}>;
  mutate(id:string,action:'pause_hooks'|'resume_hooks',body:{operation_id:string;expected_state:string}):Promise<ControlResult>;
  operation(id:string):Promise<{receipt:ControlResult|null}>;
}
export interface EpisodeContext {event_id:string;event_type:string;session_id:string;actor:string;source:string;timestamp:number;text:string;truncated?:boolean;annotation:string;active:boolean;revision:string;editable?:boolean}
export interface EpisodeControls {
 list(query:string,before?:number):Promise<{available:boolean;editable:boolean;scope:string;episodes:EpisodeContext[];next_before:number|null}>;
 detail(id:string):Promise<EpisodeContext>;
 mutate(id:string,action:'annotate'|'forget'|'restore',body:{operation_id:string;expected_revision:string;text?:string}):Promise<ControlResult>;
 operation(id:string):Promise<{receipt:ControlResult|null}>;
}
export interface SemanticClaims {available:boolean;scope:string;context_scope?:string;matching?:string;observed_at?:number;next_before:number|null;claims:{claim_id:string;subject:string;predicate:string;value:string;provenance:string;confidence:number;source_id:string;valid_from:number;valid_until:number|null;created_at:number;revision:string;active:boolean;recent_context_candidate:boolean;truncated?:boolean}[]}
export type SemanticClaimDetail=Omit<SemanticClaims['claims'][number],'recent_context_candidate'>&{actions:('correct'|'forget'|'restore')[];replaces_claim_id:string|null;changes:{action:string;actor:string;changed_at:number;replacement_claim_id:string|null}[]};
export interface SemanticClaimControls {
 detail(id:string):Promise<SemanticClaimDetail>;
 mutate(id:string,action:'correct'|'forget'|'restore',body:{operation_id:string;expected_revision:string;text?:string}):Promise<ControlResult>;
 operation(id:string):Promise<{receipt:ControlResult|null}>;
}
export interface GatewayDiagnostics {
  sessions: number; requests: Record<string, number>; approvals: Record<string, number>; handoffs: Record<string, number>;
  unknown_requests: { request_id: string; session_id: string; status: string }[]; unknown_list_limit: number;
  process_id: number; server_module_sha256: string; fingerprint_scope: string; observed_at: number; read_only: true;
}
export interface SavedMessageChunk {agent_id:string;message_id:string;session_id:string;role:string;kind:string;content:string;offset:number;end_offset:number;total_chars:number;revision:string;next_offset:number|null;previous_offset:number|null}
export interface MessageSearchPage {
  agent_id: string; next_before: string | null; matching: string;
  matches: { message_id: string; session_id: string; role: string; kind: string; title: string; timestamp: number; snippet: string; content: string; truncated: boolean;match_offset?:number;content_revision?:string }[];
}
export interface AgentMemorySnapshot { agent_id:string;editable:boolean;loaded_in_specialist_prompt:boolean;notes:string;revision:string;chars:number;prompt_chars:number;max_chars:number;prompt_truncated:boolean;versions:{revision:string;saved_at:number}[];context_preview?:string;context_scope?:string;provenance?:{source:string;digest:string;author:string;history:string};search?:{query:string;matches:{line:number;text:string;within_prompt_budget:boolean}[];truncated:boolean;scope:string} }
export interface AgentMemoryControls {
  read(id:string,query?:string):Promise<AgentMemorySnapshot>;
  mutate(id:string,body:{operation_id:string;expected_revision:string;action:'replace';text:string}|{operation_id:string;expected_revision:string;action:'restore';restore_revision:string}|{operation_id:string;expected_revision:string;action:'forget'}):Promise<ControlResult&{agent_id?:string;revision?:string}>;
  operation(id:string):Promise<{receipt:(ControlResult&{agent_id?:string;revision?:string})|null}>;
}
export interface AgentKnowledgeSnapshot {
  limits: { max_documents: number; context_chars: number };
  agent_id: string; revision: number; editable: boolean;
  documents: { id: string; revision: number; digest: string }[];
  available: { id: string; title: string; revision: number; digest: string; archived: boolean }[];
}
export interface AgentKnowledgeControls {
  read(id: string): Promise<AgentKnowledgeSnapshot>;
  save(id: string, body: { expected_revision: number; document_ids: string[] }): Promise<AgentKnowledgeSnapshot>;
}
export interface WorkflowDefinition { format: string; name: string; description: string; steps: { title: string; instruction: string }[] }
export interface WorkflowDocument { id: string; revision: number; digest: string; archived: boolean; definition: WorkflowDefinition }
export type WorkflowAction = "create" | "save" | "archive" | "restore" | "propose";
export interface WorkflowReceipt extends ControlResult { workflow?: WorkflowDocument; task?: { task_id: string; status: string; authorized: boolean } | null }
export interface WorkflowControls {
  list(): Promise<{ workflows: { id: string; title: string; revision: number; archived: boolean }[]; format: string; limits: { steps: number; bytes: number } }>;
  read(id: string): Promise<WorkflowDocument>;
  mutate(action: WorkflowAction, id: string, body: Record<string, unknown>): Promise<WorkflowReceipt>;
  operation(id: string): Promise<{ receipt: WorkflowReceipt | null }>;
}
export interface ChannelDeliveries {initialized:boolean;scope:string;next_before:number|null;deliveries:{id:string;run_id:string;state:string;claimed_at:string;completed_at:string|null;delivery_verified:false;message_id?:string;message_ids:string[];reply_to_message_id?:string;session_id?:string;request_id?:string}[]}
export interface ChannelSnapshot {
  channels: { binding?: {revision:number;agent_id:string|null}|null; active_binding?: {revision:number;agent_id:string|null}|null; active_handlers?:number; id: string; name: string; catalog_maturity: string; adapter_registered: boolean; bridge_registered: boolean; thread_state: string; connection_health: "not_probed"; delivery_verified: false; actions: string[] }[];
  scope: "current_gateway_process_only";
}
export interface TaskProposalReceipt { task_id: string; status: string; replayed: boolean; request_id: string; origin_session_id: string }
export interface JaegerSource {
  semanticClaimControls?:SemanticClaimControls;
  episodes?: EpisodeControls;
  semanticClaims?(options:{query:string;includeInactive:boolean;before?:number}):Promise<SemanticClaims>;
  plugins?:PluginControls;
  channelControls?: {
    mutate(id:string,action:'bind'|'connect'|'disconnect',body:Record<string,unknown>):Promise<ControlResult>;
    operation(id:string):Promise<{receipt:ControlResult|null}>;
  };
  channelDeliveries?(before?:number):Promise<ChannelDeliveries>;
  channels?(): Promise<ChannelSnapshot>;
  workflows?: WorkflowControls;
  agentKnowledge?: AgentKnowledgeControls;
  savedMessage?(agentId:string,messageId:string,offset:number,revision?:string):Promise<SavedMessageChunk>;
  searchMessages?(agentId: string, query: string, before?: string): Promise<MessageSearchPage>;
  diagnosticCapture?:import('./diagnosticCapture').DiagnosticCaptureControls;
  diagnostics?(): Promise<GatewayDiagnostics>;
  tools?(query?: string): Promise<ToolInventory>;
  specialistControls?: SpecialistControls;
  sessionQueue?: SessionQueue;
  messageReactions?: {
    load(sessionId: string): Promise<ReactionSnapshot>;
    save(sessionId: string, body: { request_id: string; role: "user" | "assistant"; emoji: string; active: boolean }): Promise<ReactionSnapshot>;
  };
  library?: LibraryControls;
  skillDetail?(name: string, category: string): Promise<SkillDetail>;
  mcpControls?: {
    mutate(id:string,action:'disconnect'|'reconnect',body:{operation_id:string;expected_state:string}):Promise<ControlResult>;
    operation(id:string):Promise<{receipt:ControlResult|null}>;
  };
  mcpResources?:MCPResources;
  agentMemory?:AgentMemoryControls;
  notifications?: Notifications;
  sessionFiles?: SessionFiles;
  skills?(query?: string): Promise<{ skills: { name: string; category: string; description: string; lifecycle: string }[]; count: number }>;
  schedules?: ScheduleControls;
  modelSettings?: ModelSettings;
  connectApps?: {
    list(): Promise<ConnectAppsListing>;
    state(id: string): Promise<{ id: string; state: ConnectedApp["state"] }>;
    install(id: string): Promise<{ id?: string; state?: ConnectedApp["state"] }>;
  };
  /** Read-only same-ID acceptance and terminal-outcome lookup. */
  requestStatus?(sessionId: string, requestId: string): Promise<RequestSnapshot>;
  sessionControl?(sessionId: string): Promise<{ latest_request?: { request_id: string; status: string } | null }>;
  readonly kind: "live" | "mock";
  agents(): Promise<Agent[]>;
  agentsSummary(): Promise<AgentSummary[]>;
  sessions(query?: { agent_id?: string }): Promise<SessionRow[]>;
  session(id: string): Promise<SessionDetail>;
  createSession(body: { agent_id?: string; title?: string }): Promise<SessionRow>;
  /** PATCH /v1/sessions/{id}: rename or archive a chat. */
  updateSession(id: string, body: { title?: string; archived?: boolean }): Promise<void>;
  /** POST /v1/agents: a new specialist the lead can hand work to. */
  /** Agent context-menu actions (agentActions.ts); optional, gated by agentCaps. */
  agentActions?: AgentActions;
  agentCreationStatus?(operationId: string): Promise<{ receipt: { ok: boolean; agent?: Agent; error?: string } | null }>;
  createAgent(body: { template_id?: string; template_version?: number; operation_id?: string; name: string; display_name?: string; role?: string; metadata?: Record<string, unknown> }): Promise<Agent>;
  /** The specialist's side of one hand-off: its worker session and messages. */
  replyHandoff?(handoffId: string, task: string, requestId: string): Promise<Handoff>;
  handoffExchange(handoffId: string): Promise<HandoffExchange>;
  /** POST /v1/sessions/{id}/turns. `start_event_id` is the durable cursor of
   * this turn's turn.start (stream from start_event_id - 1). */
  send(sessionId: string, text: string, requestId: string, attachmentIds?: string[]): Promise<TurnReceipt>;
  /** POST /v1/sessions/{id}/attachments: register a workspace file (the gateway sizes and hashes it). */
  addAttachment(sessionId: string, body: { path: string; filename?: string; mime_type?: string }): Promise<{ attachment_id: string }>;
  /** PROVISIONAL (bytes upload, gateway-side staging): the same endpoint with the file's bytes instead
   * of a path. Only called when the bytes-upload flag is on (composer.bytesUploadEnabled). */
  /** POST /v1/sessions/{id}/attachments/upload (bytes, 25 MB max): 201 → the stored file. 404/405 = not
   * supported by this gateway; 413 = too large. */
  uploadAttachment?(sessionId: string, body: { name: string; mime: string; data_base64: string }, idempotencyKey?: string): Promise<UploadedAttachment>;
  cancel(sessionId: string, requestId?: string): Promise<void>;
  pendingApprovals?(sessionId: string): Promise<PendingApproval[]>;
  approve(sessionId: string, approvalId: string, approved: boolean): Promise<void>;
  tasks(): Promise<Task[]>;
  taskPresentation?: {
    change(id:string,body:import("./types").TaskPresentationIntent):Promise<import("./types").TaskPresentationReceipt>;
    operation(id:string,operationId:string):Promise<{receipt:import("./types").TaskPresentationReceipt|null}>;
  };
  agentHome?(agentId: string): Promise<{ session_id: string; agent_id: string }>;
  taskActions?: {
    create(body: { session_id: string; goal: string; request_id: string; proposal: true }): Promise<TaskProposalReceipt>;
    lookup?(sessionId: string, requestId: string): Promise<{ session_id: string; request_id: string; tasks: Task[] }>;
    edit(id: string, goal: string, expected_updated_at: number): Promise<Task>;
    approve(id: string, expected_updated_at: number): Promise<void>;
    cancel(id: string): Promise<void>;
  };
  handoffs(query?: { session_id?: string }): Promise<Handoff[]>;
  /** Its own home-chat implementation, when the source has one (dev mock only). */
  homeSessions?(opts: HomeOptions): HomeSessions;
  /** Rich transcript, when the source has one (dev mock only). */
  transcript?(sessionId: string): ChatSession | undefined;
  /** Session SSE (`/v1/sessions/{id}/stream?last_event_id=<cursor>`). Resolves
   * when the stream ends or `signal` aborts; throws GatewayError on HTTP errors. */
  /** PROPOSED global event stream (agent.updated/created/deleted, section.updated/deleted, agent.unread); the
   * channel is not in the spec yet (GET /v1/events assumed). Optional: without it the roster polls. */
  globalEvents?(onEvent: (event: GatewayEvent) => void, signal: AbortSignal): Promise<void>;
  stream(sessionId: string, cursor: number | undefined, onEvent: (event: GatewayEvent) => void, signal: AbortSignal): Promise<void>;
}

export interface TurnReceipt {
  request_id: string;
  turn_id?: string;
  start_event_id?: number;
  status?: string;
  replayed?: boolean;
}
