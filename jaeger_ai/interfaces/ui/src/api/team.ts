/* Helper roster API (Gateway /v1/team, jaeger_ai/core/gateway/team_routes.py). */
export interface TeamAgent {
  id: string; name: string; display_name: string; role: string; team: string | null;
  description: string; persona: string; skills: string[]; tools: string[];
  avatar: { seed: string; url: string | null }; pack: string | null;
  status: string; activity: { status: string; turn_id?: string; since?: number } | null;
}
export interface HelperTokens { prompt: number; completion: number; total: number; reported: boolean; cost_usd: number | null }
export interface TeamHandoff { id: string; kind?: "call_agent" | "delegate"; from_agent_id: string; to_agent_id: string; status: string; task: string; session_id?: string | null; created_at?: number; updated_at?: number;
  /** Inner-helper runs (kind "delegate"): usage, a result preview and the saved result file. */
  tokens?: HelperTokens | null; summary?: string | null; result_path?: string | null; via?: string | null }
export interface TeamSnapshot { agents: TeamAgent[]; handoffs: TeamHandoff[] }
export interface TeamApi {
  snapshot(): Promise<TeamSnapshot>;
}
