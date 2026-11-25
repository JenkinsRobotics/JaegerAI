/**
 * Write-ahead SessionStore combining optimistic message submission,
 * SeqCursor deduplication, and StreamingDeltaBatcher coalescing.
 */

import {
  SeqCursor,
  createInitialSessionState,
  reduceSessionEvent,
  type ChatMessage,
  type GatewayEventEnvelope,
  type SessionStreamState,
} from "@jaeger/ui-protocol";
import { StreamingDeltaBatcher } from "./batcher";
import type { GatewayTransport } from "./transport";

export type SessionListener = (state: SessionStreamState) => void;

export class SessionStore {
  private state: SessionStreamState;
  private readonly cursor: SeqCursor;
  private readonly transport: GatewayTransport;
  private readonly listeners = new Set<SessionListener>();
  private readonly batcher: StreamingDeltaBatcher<GatewayEventEnvelope>;

  constructor(sessionId: string, transport: GatewayTransport, initialSeq = 0) {
    this.state = createInitialSessionState(sessionId);
    this.cursor = new SeqCursor(initialSeq);
    this.transport = transport;
    this.batcher = new StreamingDeltaBatcher<GatewayEventEnvelope>((frames) => {
      let next = this.state;
      for (const frame of frames) {
        const res = this.cursor.advance(frame.seq);
        if (frame.seq === 0 || res.accepted) {
          next = reduceSessionEvent(next, frame);
        }
      }
      if (next !== this.state) {
        this.state = next;
        this.emit();
      }
    });
  }

  getSnapshot(): SessionStreamState {
    return this.state;
  }

  get lastSeq(): number {
    return this.cursor.lastSeq;
  }

  subscribe(listener: SessionListener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  applyEvent(envelope: GatewayEventEnvelope, immediate = false): void {
    if (immediate) {
      const res = this.cursor.advance(envelope.seq);
      if (envelope.seq === 0 || res.accepted) {
        this.state = reduceSessionEvent(this.state, envelope);
        this.emit();
      }
      return;
    }
    this.batcher.push(envelope);
  }

  flush(): void {
    this.batcher.flushNow();
  }

  /**
   * Write-ahead optimistic prompt submission with rollback on transport failure.
   */
  async sendPrompt(prompt: string, requestId?: string): Promise<string> {
    const rid =
      requestId ||
      (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
        ? `req_${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`
        : `req_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`);

    const optimisticMsg: ChatMessage = {
      id: `opt_${rid}`,
      session_id: this.state.sessionId,
      role: "user",
      content: prompt,
      parts: [{ type: "text", text: prompt }],
      created_at: Date.now(),
      request_id: rid,
      optimistic: true,
    };

    const prevMessages = this.state.messages;
    this.state = {
      ...this.state,
      status: "queued",
      lastError: null,
      messages: [...prevMessages, optimisticMsg],
    };
    this.emit();

    try {
      await this.transport.submitRun(this.state.sessionId, prompt, rid);
      this.state = {
        ...this.state,
        messages: this.state.messages.map((m) =>
          m.id === optimisticMsg.id ? { ...m, optimistic: false } : m,
        ),
      };
      this.emit();
      return rid;
    } catch (err) {
      this.state = {
        ...this.state,
        status: "failed",
        lastError: err instanceof Error ? err.message : String(err),
        messages: prevMessages,
      };
      this.emit();
      throw err;
    }
  }

  dispose(): void {
    this.batcher.dispose();
    this.listeners.clear();
  }

  private emit(): void {
    for (const listener of this.listeners) {
      listener(this.state);
    }
  }
}
