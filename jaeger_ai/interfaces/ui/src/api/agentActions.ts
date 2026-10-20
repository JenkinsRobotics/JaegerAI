/* Agent menu capability negotiation. Only explicit ui_actions from the server enable
 * remote actions; absent/false is unavailable. Device-local pins/seen marks are separate.
 * Canonical Gateway currently supports read through POST /v1/agents/{id}/seen only. */
import type { Agent } from "./types";

export interface Section { id: string; name: string; order?: number }
export interface AgentPatch { display_name?: string | null; archived?: boolean; pinned?: boolean; hidden?: boolean; section_id?: string | null; enabled?: boolean }

export interface AgentActions {
  setPrimary?(agentId: string, expectedId: string): Promise<void>;
  markUnread?(agentId: string): Promise<void>;
  savePins?(agentIds: string[], expectedIds: string[]): Promise<void>;
  markRead(agentId: string, messageId: string | null): Promise<void>;
  patchAgent(agentId: string, body: AgentPatch): Promise<void>;
  sections(): Promise<Section[]>;
  createSection(name: string): Promise<Section>;
  duplicate(agentId: string, name?: string): Promise<Agent>;
  remove(agentId: string): Promise<void>;
  template(agentId: string): Promise<unknown>;
}

export interface AgentCaps { primary?: boolean; unread?: boolean; rename: boolean; read: boolean; pin: boolean; hide: boolean; sections: boolean; duplicate: boolean; remove: boolean; template: boolean }
export const NO_CAPS: AgentCaps = { primary: false, unread: false, rename: false, read: false, pin: false, hide: false, sections: false, duplicate: false, remove: false, template: false };

/** Intersection of explicit actions for the selected agents; no identity-field guessing. */
export function agentCaps(agents: Agent[], actions?: AgentActions): AgentCaps {
  if (!actions || !agents.length) return NO_CAPS;
  return Object.fromEntries(Object.keys(NO_CAPS).map((key) => [key, agents.every((a) => a.ui_actions?.[key as keyof AgentCaps] === true)])) as unknown as AgentCaps;
}

/** Execution lead/system protections are independent of the presentation-primary flag. */
export const isProtected = (a: Pick<Agent, "id" | "primary" | "role">) => a.role === "lead" || a.id === "native:jaeger";


/** Resolve a conversation, never substitute an agent ID for its home/session ID. */
export async function conversationIdForAgent(agentId: string, home: (id: string) => Promise<string>, selected?: { agentId: string; sessionId: string }): Promise<string> {
  const id = selected?.agentId === agentId ? selected.sessionId : await home(agentId);
  if (typeof id !== "string" || !id.trim()) throw new Error("Conversation ID unavailable");
  return id;
}
