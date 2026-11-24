/**
 * ui-contracts: Composable Gateway capability interfaces decomposed from JaegerSource.
 *
 * Architectural boundaries:
 * - One Gateway remains authoritative for execution, memory, tasks, and permissions.
 * - Feature modules declare required Gateway capabilities via UiCapabilityKey.
 * - Unsupported capabilities render honestly unavailable — never fake or fallback data.
 */
import type { JaegerSource } from "../api/source";

export type ChatSessionCapability = Pick<
  JaegerSource,
  | "kind"
  | "sessions"
  | "session"
  | "createSession"
  | "updateSession"
  | "deleteSession"
  | "send"
  | "cancel"
  | "stream"
  | "globalEvents"
  | "sessionQueue"
  | "messageReadState"
  | "messageReactions"
  | "switchMessageVersion"
  | "searchMessages"
  | "savedMessage"
  | "operatorSession"
  | "sessionControl"
  | "requestStatus"
  | "acknowledgeUnknown"
>;

export type ApprovalCapability = Pick<
  JaegerSource,
  | "approve"
  | "pendingApprovals"
  | "approvalStatus"
  | "clarifications"
  | "clarificationStatus"
  | "answerClarify"
>;

export type AgentOrchestrationCapability = Pick<
  JaegerSource,
  | "agents"
  | "agentsSummary"
  | "createAgent"
  | "agentActions"
  | "agentCreationStatus"
  | "agentHome"
  | "handoffs"
  | "handoffExchange"
  | "delegation"
  | "handoffStops"
  | "replyHandoff"
  | "replyHandoffCommand"
  | "originalHandoffReply"
  | "specialistControls"
  | "team"
  | "organization"
>;

export type TaskWorkflowCapability = Pick<
  JaegerSource,
  | "tasks"
  | "taskActions"
  | "taskPresentation"
  | "schedules"
  | "workflows"
  | "webhooks"
  | "finance"
>;

export type ToolSkillPluginCapability = Pick<
  JaegerSource,
  | "tools"
  | "skills"
  | "skillDetail"
  | "managedSkills"
  | "skillRevisions"
  | "mcpControls"
  | "mcpResources"
  | "mcpConfiguration"
  | "plugins"
  | "connectApps"
>;

export type MemoryLibraryCapability = Pick<
  JaegerSource,
  | "library"
  | "agentMemory"
  | "agentKnowledge"
  | "memoryFacts"
  | "ownerProfile"
  | "episodes"
  | "semanticClaims"
  | "semanticClaimControls"
>;

export type RuntimeDiagnosticsCapability = Pick<
  JaegerSource,
  | "connectionInfo"
  | "diagnostics"
  | "diagnosticCapture"
  | "policySources"
  | "computers"
  | "updatePlan"
  | "runtimeAutonomy"
  | "setRuntimeAutonomy"
  | "runtimeTier"
  | "setRuntimeTier"
  | "modelSettings"
  | "channels"
  | "channelControls"
  | "channelDeliveries"
  | "notifications"
  | "processStream"
  | "processHistory"
>;

export type FileAttachmentCapability = Pick<
  JaegerSource,
  "addAttachment" | "uploadAttachment" | "sessionFiles" | "taskArtifacts"
>;

export type UiCapabilityKey =
  | "chat.sessions"
  | "chat.approvals"
  | "chat.queue"
  | "agents.catalog"
  | "agents.team"
  | "tasks.board"
  | "tasks.workflows"
  | "tools.inventory"
  | "tools.mcp"
  | "tools.plugins"
  | "skills.catalog"
  | "memory.facts"
  | "memory.library"
  | "memory.episodes"
  | "settings.models"
  | "settings.runtime"
  | "settings.channels"
  | "diagnostics.gateway"
  | "diagnostics.process"
  | "files.attachments";

const CAPABILITY_CHECKS: Record<UiCapabilityKey, (source: JaegerSource) => boolean> = {
  "chat.sessions": (s) => typeof s.sessions === "function" && typeof s.send === "function" && typeof s.stream === "function",
  "chat.approvals": (s) => typeof s.approve === "function",
  "chat.queue": (s) => Boolean(s.sessionQueue),
  "agents.catalog": (s) => typeof s.agents === "function",
  "agents.team": (s) => Boolean(s.team),
  "tasks.board": (s) => typeof s.tasks === "function",
  "tasks.workflows": (s) => Boolean(s.workflows),
  "tools.inventory": (s) => typeof s.tools === "function",
  "tools.mcp": (s) => Boolean(s.mcpControls || s.mcpConfiguration || s.mcpResources),
  "tools.plugins": (s) => Boolean(s.plugins),
  "skills.catalog": (s) => typeof s.skills === "function" || Boolean(s.managedSkills),
  "memory.facts": (s) => Boolean(s.memoryFacts || s.semanticClaims || s.agentMemory),
  "memory.library": (s) => Boolean(s.library),
  "memory.episodes": (s) => Boolean(s.episodes),
  "settings.models": (s) => Boolean(s.modelSettings),
  "settings.runtime": (s) => typeof s.runtimeAutonomy === "function" || typeof s.runtimeTier === "function",
  "settings.channels": (s) => typeof s.channels === "function",
  "diagnostics.gateway": (s) => typeof s.diagnostics === "function",
  "diagnostics.process": (s) => typeof s.processStream === "function" || typeof s.processHistory === "function",
  "files.attachments": (s) => typeof s.addAttachment === "function" || Boolean(s.sessionFiles),
};

export interface CapabilityEvaluation {
  supported: boolean;
  missing: UiCapabilityKey[];
}

/** Check whether a Gateway source satisfies all capabilities declared by a feature module. */
export function evaluateCapabilities(
  source: JaegerSource | null | undefined,
  required: readonly UiCapabilityKey[],
): CapabilityEvaluation {
  if (!source) {
    return { supported: false, missing: [...required] };
  }
  const missing = required.filter((cap) => !CAPABILITY_CHECKS[cap](source));
  return { supported: missing.length === 0, missing };
}
