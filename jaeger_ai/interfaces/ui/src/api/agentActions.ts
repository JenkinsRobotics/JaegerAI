/* Agent menu capability negotiation. Only explicit ui_actions from the server enable
 * remote actions; absent/false is unavailable. Device-local pins/seen marks are separate.
 * Canonical Gateway currently supports read through POST /v1/agents/{id}/seen only. */
import type { Agent } from "./types";

export interface Section { id: string; name: string; order?: number }
export interface AgentPatch { display_name?: string | null; archived?: boolean; pinned?: boolean; hidden?: boolean; section_id?: string | null; enabled?: boolean }

export interface AgentActions {
  savePins?(agentIds: string[], expectedIds: string[]): Promise<void>;
  markRead(agentId: string, messageId: string | null): Promise<void>;
  patchAgent(agentId: string, body: AgentPatch): Promise<void>;
  sections(): Promise<Section[]>;
  createSection(name: string): Promise<Section>;
  duplicate(agentId: string, name?: string): Promise<Agent>;
  remove(agentId: string): Promise<void>;
  template(agentId: string): Promise<unknown>;
}

export interface AgentCaps { rename: boolean; read: boolean; pin: boolean; hide: boolean; sections: boolean; duplicate: boolean; remove: boolean; template: boolean }
export const NO_CAPS: AgentCaps = { rename: false, read: false, pin: false, hide: false, sections: false, duplicate: false, remove: false, template: false };

/** Intersection of explicit actions for the selected agents; no identity-field guessing. */
export function agentCaps(agents: Agent[], actions?: AgentActions): AgentCaps {
  if (!actions || !agents.length) return NO_CAPS;
  return Object.fromEntries(Object.keys(NO_CAPS).map((key) => [key, agents.every((a) => a.ui_actions?.[key as keyof AgentCaps] === true)])) as unknown as AgentCaps;
}

/** The primary agent and native:jaeger are protected (409 protected_agent): never offer Delete for them. */
export const isProtected = (a: Pick<Agent, "id" | "primary" | "role">) => Boolean(a.primary) || a.role === "lead" || a.id === "native:jaeger";
