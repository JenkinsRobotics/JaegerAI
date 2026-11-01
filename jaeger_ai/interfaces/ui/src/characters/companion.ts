/** Companion API (J-070): gateway /v1/companion/* via the WebUI passthrough. Local models only. */
import { getJson, sendJson } from "../unified/webui";

export interface CompanionTurn { role: "user" | "assistant"; content: string }
export interface CompanionReply { reply: string; model: string; recalled: string[] }

export const companionApi = {
  chat: (id: string, message: string, history: CompanionTurn[]) =>
    sendJson<CompanionReply>("POST", `/v1/companion/${encodeURIComponent(id)}/chat`, { message, history }),
  card: (id: string) => getJson<Record<string, unknown>>(`/v1/companion/${encodeURIComponent(id)}/ccv3`),
};
