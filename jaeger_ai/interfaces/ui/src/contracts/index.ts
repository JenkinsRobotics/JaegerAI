/**
 * ui-contracts public barrel: Gateway request/response/event contracts and
 * composable capability interfaces shared across WebUI, VS Code, and macOS hosts.
 */
export * from "./capabilities";
export type {
  JaegerSource,
  TurnReceipt,
  PendingApproval,
  ClarificationSnapshot,
  RequestSnapshot,
  ModelInventory,
  ModelSettings,
  RuntimeAutonomy,
  RuntimeTier,
  GatewayDiagnostics,
  ToolInventory,
  ManagedSkill,
  SessionFile,
  TaskArtifact,
} from "../api/source";
export type {
  Agent,
  AgentSummary,
  GatewayEvent,
  Handoff,
  HandoffExchange,
  SessionDetail,
  SessionRow,
  Task,
} from "../api/types";
export type {
  HostKind,
  ChatHost,
  ChatPaneMount,
  ChatPaneOptions,
  ChatPart,
  ChatPartKind,
  ChatSession,
  ChatSessionSummary,
  ChatTurn,
  StartTurnRequest,
  TurnHandle,
  TurnState,
} from "../chat/host";
