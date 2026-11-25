/**
 * Host-neutral GatewayTransport abstraction across WebUI (HTTP+SSE), macOS (WKWebView), and VS Code.
 */

import {
  decodeSSE,
  type GatewayEventEnvelope,
  type SessionSummary,
} from "@jaeger/ui-protocol";

export interface SubmitRunResponse {
  request_id: string;
  status?: string;
}

export interface GatewayTransport {
  readonly kind: "http-sse" | "wkwebview" | "vscode";
  listSessions(): Promise<SessionSummary[]>;
  submitRun(sessionId: string, prompt: string, requestId: string): Promise<SubmitRunResponse>;
  resolveApproval(approvalId: string, decision: "approve" | "deny", note?: string): Promise<void>;
  subscribe(
    sessionId: string,
    afterSeq: number,
    onEvent: (envelope: GatewayEventEnvelope) => void,
    signal?: AbortSignal,
  ): Promise<void>;
}

export class HttpSseTransport implements GatewayTransport {
  readonly kind = "http-sse" as const;
  private readonly baseUrl: string;
  private readonly headers: Record<string, string>;

  constructor(options: { baseUrl?: string; token?: string } = {}) {
    this.baseUrl = (options.baseUrl ?? "").replace(/\/+$/, "");
    this.headers = options.token ? { Authorization: `Bearer ${options.token}` } : {};
  }

  async listSessions(): Promise<SessionSummary[]> {
    const res = await fetch(`${this.baseUrl}/v1/sessions`, { headers: this.headers });
    if (!res.ok) throw new Error(`listSessions failed (${res.status})`);
    const body = (await res.json()) as { sessions?: SessionSummary[] };
    return body.sessions ?? [];
  }

  async submitRun(sessionId: string, prompt: string, requestId: string): Promise<SubmitRunResponse> {
    const res = await fetch(`${this.baseUrl}/v1/sessions/${encodeURIComponent(sessionId)}/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...this.headers },
      body: JSON.stringify({ prompt, request_id: requestId }),
    });
    if (!res.ok) throw new Error(`submitRun failed (${res.status})`);
    return (await res.json()) as SubmitRunResponse;
  }

  async resolveApproval(approvalId: string, decision: "approve" | "deny", note = ""): Promise<void> {
    const res = await fetch(`${this.baseUrl}/v1/approvals/${encodeURIComponent(approvalId)}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...this.headers },
      body: JSON.stringify({ decision, note }),
    });
    if (!res.ok) throw new Error(`resolveApproval failed (${res.status})`);
  }

  async subscribe(
    sessionId: string,
    afterSeq: number,
    onEvent: (envelope: GatewayEventEnvelope) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const reqHeaders: Record<string, string> = { ...this.headers };
    if (afterSeq > 0) reqHeaders["Last-Event-ID"] = String(afterSeq);
    const res = await fetch(
      `${this.baseUrl}/v1/sessions/${encodeURIComponent(sessionId)}/events?after_seq=${afterSeq}`,
      { headers: reqHeaders, signal },
    );
    if (!res.ok || !res.body) throw new Error(`SSE subscribe failed (${res.status})`);
    for await (const frame of decodeSSE(res.body, signal)) {
      const seq = frame.id ? Number.parseInt(frame.id, 10) : 0;
      const payload =
        frame.data && typeof frame.data === "object"
          ? (frame.data as Record<string, unknown>)
          : { value: frame.data };
      onEvent({
        seq: Number.isFinite(seq) ? seq : 0,
        event: frame.event || "message",
        session_id: sessionId,
        payload,
      });
    }
  }
}

export interface BridgeRpcHost {
  invoke<T = unknown>(method: string, params?: Record<string, unknown>): Promise<T>;
  onEvent(listener: (envelope: GatewayEventEnvelope) => void): () => void;
}

export class WkWebViewBridgeTransport implements GatewayTransport {
  readonly kind = "wkwebview" as const;
  private readonly bridge: BridgeRpcHost;

  constructor(bridge: BridgeRpcHost) {
    this.bridge = bridge;
  }

  listSessions(): Promise<SessionSummary[]> {
    return this.bridge.invoke<SessionSummary[]>("sessions.list");
  }

  submitRun(sessionId: string, prompt: string, requestId: string): Promise<SubmitRunResponse> {
    return this.bridge.invoke<SubmitRunResponse>("runs.submit", { sessionId, prompt, requestId });
  }

  async resolveApproval(approvalId: string, decision: "approve" | "deny", note = ""): Promise<void> {
    await this.bridge.invoke("approvals.resolve", { approvalId, decision, note });
  }

  async subscribe(
    sessionId: string,
    afterSeq: number,
    onEvent: (envelope: GatewayEventEnvelope) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    await this.bridge.invoke("events.subscribe", { sessionId, afterSeq });
    return new Promise<void>((resolve) => {
      const unsub = this.bridge.onEvent((env) => {
        if (!env.session_id || env.session_id === sessionId) onEvent(env);
      });
      if (signal?.aborted) {
        unsub();
        resolve();
        return;
      }
      signal?.addEventListener(
        "abort",
        () => {
          unsub();
          resolve();
        },
        { once: true },
      );
    });
  }
}

export class VsCodeWebviewTransport implements GatewayTransport {
  readonly kind = "vscode" as const;
  private readonly bridge: BridgeRpcHost;

  constructor(bridge: BridgeRpcHost) {
    this.bridge = bridge;
  }

  listSessions(): Promise<SessionSummary[]> {
    return this.bridge.invoke<SessionSummary[]>("sessions.list");
  }

  submitRun(sessionId: string, prompt: string, requestId: string): Promise<SubmitRunResponse> {
    return this.bridge.invoke<SubmitRunResponse>("runs.submit", { sessionId, prompt, requestId });
  }

  async resolveApproval(approvalId: string, decision: "approve" | "deny", note = ""): Promise<void> {
    await this.bridge.invoke("approvals.resolve", { approvalId, decision, note });
  }

  async subscribe(
    sessionId: string,
    afterSeq: number,
    onEvent: (envelope: GatewayEventEnvelope) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    await this.bridge.invoke("events.subscribe", { sessionId, afterSeq });
    return new Promise<void>((resolve) => {
      const unsub = this.bridge.onEvent((env) => {
        if (!env.session_id || env.session_id === sessionId) onEvent(env);
      });
      if (signal?.aborted) {
        unsub();
        resolve();
        return;
      }
      signal?.addEventListener(
        "abort",
        () => {
          unsub();
          resolve();
        },
        { once: true },
      );
    });
  }
}
