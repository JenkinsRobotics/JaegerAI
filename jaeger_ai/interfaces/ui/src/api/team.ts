/* Team runtime API (Gateway /v1/team*, jaeger_ai/core/gateway/team_routes.py). */
export interface TeamAgent {
  id: string; name: string; display_name: string; role: string; team: string | null;
  description: string; persona: string; skills: string[]; tools: string[];
  avatar: { seed: string; url: string | null }; pack: string | null;
  status: string; activity: { status: string; room?: string; turn_id?: string; since?: number } | null;
}
export interface TeamRoom { session_id: string; title: string | null; members: string[]; updated_at?: number; probe: boolean; status?: string }
export interface TeamHandoff { id: string; kind?: "call_agent" | "room"; from_agent_id: string; to_agent_id: string; status: string; task: string; session_id?: string | null; room_title?: string | null; created_at?: number; updated_at?: number }
export interface TeamSnapshot { agents: TeamAgent[]; rooms: TeamRoom[]; handoffs: TeamHandoff[]; limits: Record<string, number> }
export interface RoomMessage { id: number; role: string; kind: string; content: string; sender_agent_id: string | null; created_at?: number; timestamp?: number; links?: Record<string, unknown> }
export interface RoomDetail { room: { session_id: string; title: string; members: string[]; probe: boolean }; messages: RoomMessage[] }
export interface TeamApi {
  snapshot(): Promise<TeamSnapshot>;
  createRoom(body: { title: string; members: string[]; probe?: boolean }): Promise<{ session_id: string; title: string; members: string[] }>;
  room(sessionId: string): Promise<RoomDetail>;
  say(sessionId: string, text: string): Promise<{ request_id: string; session_id: string }>;
}
