/** Companion API (J-070): gateway /v1/companion/* via the WebUI passthrough. Local models only. */
import { csrfHeader } from "../api/gateway";
import { getJson, sendJson } from "../unified/webui";

export interface CompanionTurn { role: "user" | "assistant"; content: string }
export interface CompanionReply { reply: string; model: string; recalled: string[]; interrupted?: boolean }

export interface CouncilTurn {
  character_id: string;
  name: string;
  reply: string;
  recalled_count?: number;
}

export interface CouncilSynthesis {
  character_id: string;
  name: string;
  reply: string;
  model?: string;
}

export interface CouncilReply {
  mode: "council";
  topic: string;
  model: string;
  turns: CouncilTurn[];
  truth_synthesis: CouncilSynthesis | null;
}

export interface StreamHandlers {
  onDelta?: (delta: string) => void;
  signal?: AbortSignal;
}

async function parseSseStream(
  response: Response,
  onDelta?: (delta: string) => void,
): Promise<CompanionReply> {
  const reader = response.body?.getReader();
  if (!reader) {
    const data = (await response.json()) as CompanionReply;
    return data;
  }
  const decoder = new TextDecoder();
  let buffer = "";
  let accumulated = "";
  let finalReply: CompanionReply | null = null;

  const processBlock = (block: string) => {
    const dataLines = block
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trim());
    if (!dataLines.length) return;
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
    } catch {
      return;
    }
    const kind = String(payload.type || "");
    if (kind === "delta" && typeof payload.text === "string") {
      accumulated += payload.text;
      onDelta?.(payload.text);
    } else if (kind === "done") {
      finalReply = {
        reply: typeof payload.reply === "string" ? payload.reply : accumulated,
        model: String(payload.model || ""),
        recalled: Array.isArray(payload.recalled) ? (payload.recalled as string[]) : [],
        interrupted: Boolean(payload.interrupted),
      };
    } else if (kind === "error") {
      throw new Error(String(payload.error || "local model stream error"));
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split(/\r?\n\r?\n/);
    buffer = parts.pop() ?? "";
    for (const part of parts) processBlock(part);
  }
  if (buffer.trim()) processBlock(buffer);
  return finalReply ?? { reply: accumulated, model: "", recalled: [] };
}

export const companionApi = {
  chat: (id: string, message: string, history: CompanionTurn[]) =>
    sendJson<CompanionReply>("POST", `/v1/companion/${encodeURIComponent(id)}/chat`, { message, history }),
  stream: async (
    id: string,
    message: string,
    history: CompanionTurn[],
    handlers: StreamHandlers = {},
  ): Promise<CompanionReply> => {
    const path = `/v1/companion/${encodeURIComponent(id)}/chat/stream`;
    const r = await fetch(path, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream, application/json",
        ...csrfHeader("POST"),
      },
      body: JSON.stringify({ message, history }),
      signal: handlers.signal,
    });
    if (!r.ok) {
      const text = await r.text();
      let errMsg = `${path}: HTTP ${r.status}`;
      try {
        const parsed = text ? (JSON.parse(text) as { error?: string }) : {};
        if (parsed.error) errMsg = parsed.error;
      } catch {
        // Keep HTTP error message
      }
      throw new Error(errMsg);
    }
    const contentType = (r.headers.get("content-type") || "").toLowerCase();
    if (contentType.includes("text/event-stream")) {
      return parseSseStream(r, handlers.onDelta);
    }
    return (await r.json()) as CompanionReply;
  },
  council: (
    characters: string[],
    topic: string,
    options: { history?: CompanionTurn[]; includeTruthSynthesis?: boolean } = {},
  ) =>
    sendJson<CouncilReply>("POST", "/v1/companion/council", {
      characters,
      topic,
      history: options.history ?? [],
      include_truth_synthesis: options.includeTruthSynthesis ?? true,
    }),
  card: (id: string) => getJson<Record<string, unknown>>(`/v1/companion/${encodeURIComponent(id)}/ccv3`),
};
