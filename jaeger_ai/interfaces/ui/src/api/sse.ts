/* Typed port of decodeSSE from jaeger_ai/interfaces/ide/gateway.js.
 * Parses `id:` / `event:` / `data:` frames from a fetch body. A blank line ends
 * a frame; data lines are joined with "\n" and parsed as JSON. */

export interface SSEFrame {
  id?: string;
  event?: string;
  data: unknown;
}

const MAX_BUFFER = 8 * 1024 * 1024;

export function parseSSEChunk(buffer: string): { frames: SSEFrame[]; rest: string } {
  const frames: SSEFrame[] = [];
  const normalized = buffer.replace(/\r\n/g, "\n");
  const blocks = normalized.split("\n\n");
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    let id: string | undefined;
    let event: string | undefined;
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (!line || line.startsWith(":")) continue;
      const colon = line.indexOf(":");
      const field = colon < 0 ? line : line.slice(0, colon);
      const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
      if (field === "data") data.push(value);
      else if (field === "event") event = value;
      else if (field === "id") id = value;
    }
    if (!data.length) continue;
    const raw = data.join("\n");
    let parsed: unknown = raw;
    try { parsed = JSON.parse(raw); } catch { /* keep raw text */ }
    frames.push({ id, event, data: parsed });
  }
  return { frames, rest };
}

export async function* decodeSSE(body: ReadableStream<Uint8Array>, signal?: AbortSignal, idleMs = 30_000): AsyncGenerator<SSEFrame> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (!signal?.aborted) {
      let timer: ReturnType<typeof setTimeout> | undefined;
      let result: ReadableStreamReadResult<Uint8Array>;
      try {
        result = await Promise.race([
          reader.read(),
          new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error("Event transport idle; reconnecting to the same request")), idleMs); }),
        ]);
      } finally { if (timer !== undefined) clearTimeout(timer); }
      const { value, done } = result;
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      if (buffer.length > MAX_BUFFER) throw new Error("SSE frame exceeds 8 MB");
      const { frames, rest } = parseSSEChunk(buffer);
      buffer = rest;
      yield* frames;
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
