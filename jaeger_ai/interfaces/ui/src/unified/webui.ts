/** Same-origin JSON helpers for WebUI-owned endpoints (unified UI). Mutations carry the CSRF header. */
import { csrfHeader } from "../api/gateway";

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(path, { credentials: "include", headers: { Accept: "application/json" }, signal });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json() as Promise<T>;
}

export async function sendJson<T>(method: "POST" | "PUT" | "DELETE", path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, { method, credentials: "include", headers: { "Content-Type": "application/json", Accept: "application/json", ...csrfHeader(method) }, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await r.text();
  const data = text ? JSON.parse(text) : {};
  if (!r.ok) throw new Error((data as { error?: string }).error || `${path}: HTTP ${r.status}`);
  return data as T;
}

export interface MetricSample { t: number; cpu: number | null; mem: number | null; disk: number | null; gpu: number | null; mem_used?: number; mem_total?: number; disk_used?: number; disk_total?: number; cores?: number; gateway: { ok: boolean; latency_ms: number | null } }
export interface Metrics { now: MetricSample; history: MetricSample[]; interval: number; source: string }
export interface SystemStatus { gateway: { ok: boolean; latency_ms: number | null }; tailscale: { available: boolean; state?: string; host?: string; online?: boolean; peers?: number; peers_online?: number } }
