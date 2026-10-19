/* Agent context-menu actions, exactly the spec sent to the Gateway bot (2026-10-19):
 *   POST /v1/agents/{id}/read {message_id|null} · PATCH /v1/agents/{id} {pinned}|{hidden}|{section_id}|{enabled}
 *   GET/POST /v1/sections · PATCH/DELETE /v1/sections/{id} · POST /v1/agents/{id}/duplicate {name?} → 201 agent
 *   DELETE /v1/agents/{id} → 204 (soft delete; 409 protected_agent for the primary and native:jaeger)
 *   GET /v1/agents/{id}/template
 * Capabilities are read from the agents payload: today's gateway sends none of the new fields, so every new item
 * is hidden there (Mark Read and Pin fall back to the device-local seen mark and pins). */
import type { Agent } from "./types";

export interface Section { id: string; name: string; order?: number }
export interface AgentPatch { pinned?: boolean; hidden?: boolean; section_id?: string | null; enabled?: boolean }

export interface AgentActions {
  markRead(agentId: string, messageId: string | null): Promise<void>;
  patchAgent(agentId: string, body: AgentPatch): Promise<void>;
  sections(): Promise<Section[]>;
  createSection(name: string): Promise<Section>;
  duplicate(agentId: string, name?: string): Promise<Agent>;
  remove(agentId: string): Promise<void>;
  template(agentId: string): Promise<unknown>;
}

export interface AgentCaps { read: boolean; pin: boolean; hide: boolean; sections: boolean; duplicate: boolean; remove: boolean; template: boolean }
export const NO_CAPS: AgentCaps = { read: false, pin: false, hide: false, sections: false, duplicate: false, remove: false, template: false };

/** Which server-backed items this gateway supports, from the fields its GET /v1/agents items carry. */
export function agentCaps(agents: Agent[], actions?: AgentActions): AgentCaps {
  if (!actions || !agents.length) return NO_CAPS;
  const has = (k: keyof Agent) => agents.some((a) => k in a);
  const spec = has("primary") && has("unread_count");
  return { read: has("unread_count"), pin: has("pinned"), hide: has("hidden") && spec, sections: has("section_id"), duplicate: spec, remove: spec, template: spec };
}

/** The primary agent and native:jaeger are protected (409 protected_agent): never offer Delete for them. */
export const isProtected = (a: Pick<Agent, "id" | "primary">) => Boolean(a.primary) || a.id === "native:jaeger";
