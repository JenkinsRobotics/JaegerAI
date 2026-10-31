/** Ollama model helpers for Models / Compare / Documents (unified UI). */
import { getJson, sendJson } from "./webui";
import { csrfHeader } from "../api/gateway";

export interface LocalModel { name: string; size: number; modified_at?: string; family?: string; parameters?: string; quantization?: string; format?: string; context?: number; loaded: boolean; vram?: number }
export interface Pull { name: string; state: "running" | "done" | "error"; status: string; completed: number; total: number }
export interface Hardware { chip: string | null; memory: number | null; cpu_cores: number | null; perf_cores: number | null; gpu_cores: number | null; note: string }

/** Ollama "cloud" models are tiny manifests that run remotely. */
export const isCloud = (m: Pick<LocalModel, "name" | "size">) => /(^|[-:])cloud\b/.test(m.name) || m.size < 4096;
export const isEmbedding = (m: Pick<LocalModel, "name" | "family">) => /embed/i.test(m.name) || /bert/i.test(m.family ?? "");

/** Fit on Apple unified memory: weights + ~20% for context against ~75% of RAM usable by the GPU. */
export function fit(size: number, memory: number | null): "cloud" | "good" | "tight" | "too-big" | "unknown" {
  if (size < 4096) return "cloud";
  if (!memory) return "unknown";
  const need = size * 1.2, budget = memory * 0.75;
  return need <= budget * 0.6 ? "good" : need <= budget ? "tight" : "too-big";
}
export const gb = (b?: number | null) => (b == null ? "–" : b < 1e6 ? "remote" : `${(b / 1e9).toFixed(1)} GB`);

export const loadModels = () => getJson<{ models: LocalModel[]; pulls: Pull[] }>("/v1/models/local");
export const loadHardware = () => getJson<Hardware>("/v1/models/hardware");

// ── Provider catalog (WebUI /api/models: only configured providers appear) ──
export interface CatalogModel { id: string; name: string; label?: string; size_gb?: number; capabilities?: string[]; multimodal?: boolean; tool_use?: boolean }
export interface CatalogGroup { provider: string; provider_id: string; status?: string; credentials_available?: boolean; endpoint?: string; host?: string; models: CatalogModel[] }
export interface Catalog { active_provider?: string; default_model?: string; default_model_full_id?: string; groups: CatalogGroup[] }
export interface ProviderKey { id: string; has_key: boolean; key_source?: string; is_oauth?: boolean }
export const loadCatalog = () => getJson<Catalog>("/api/models");
export const loadProviderKeys = () => getJson<{ providers: ProviderKey[] }>("/api/providers");

/** Jaeger's main model setting (the same call Settings → Models makes). */
export const setDefaultModel = (model: string, provider: string) => sendJson("POST", "/api/default-model", { model, provider });
export const isDefault = (c: Catalog | null | undefined, providerId: string, name: string) =>
  !!c && (c.default_model_full_id === `@${providerId}:${name}` || (c.default_model === name && c.active_provider === providerId));

export interface Row { key: string; name: string; providerId: string; local?: LocalModel; catalog?: CatalogModel }
/** One row per model per provider; Ollama groups are enriched with the Mac's real /api/tags details. */
export interface Group { id: string; title: string; group?: CatalogGroup; rows: Row[] }
export function inventory(catalog: Catalog | null, local: LocalModel[] | null): Group[] {
  const byName = new Map((local ?? []).map((m) => [m.name, m]));
  const groups: Group[] = (catalog?.groups ?? []).map((g): Group => ({ id: g.provider_id, title: g.provider, group: g, rows: g.models.map((c) => ({ key: `${g.provider_id}:${c.name}`, name: c.name, providerId: g.provider_id, catalog: c, local: g.provider_id.startsWith("ollama") ? byName.get(c.name) : undefined })) }));
  // Ollama models the catalog doesn't list (e.g. embeddings) still belong to the local inventory.
  const listed = new Set(groups.filter((g) => g.id.startsWith("ollama")).flatMap((g) => g.rows.map((r) => r.name)));
  const extra = (local ?? []).filter((m) => !listed.has(m.name));
  if (extra.length || (!catalog && local)) {
    const loc = groups.find((g) => g.id === "ollama-local");
    const rows: Row[] = extra.map((m) => ({ key: `${isCloud(m) ? "ollama-cloud" : "ollama-local"}:${m.name}`, name: m.name, providerId: isCloud(m) ? "ollama-cloud" : "ollama-local", local: m }));
    if (loc) loc.rows.push(...rows.filter((r) => r.providerId === "ollama-local"));
    else if (rows.some((r) => r.providerId === "ollama-local")) groups.unshift({ id: "ollama-local", title: "Ollama Local", group: undefined, rows: rows.filter((r) => r.providerId === "ollama-local") });
    const cl = groups.find((g) => g.id === "ollama-cloud");
    const cloudRows = rows.filter((r) => r.providerId === "ollama-cloud");
    if (cl) cl.rows.push(...cloudRows); else if (cloudRows.length) groups.push({ id: "ollama-cloud", title: "Ollama Cloud", group: undefined, rows: cloudRows });
  }
  return groups.sort((a, b) => Number(b.id === "ollama-local") - Number(a.id === "ollama-local"));
}

// ── Compare ──
export interface Metrics { elapsed_s: number; ttft_s: number | null; eval_count?: number | null; prompt_eval_count?: number | null; tokens_per_s?: number | null; load_s?: number; cost_usd?: number | null }
export type CompareEvent = { type: "start"; model: string; local: boolean } | { type: "delta" | "thinking"; text: string } | ({ type: "done"; model: string } & Metrics) | { type: "error"; error: string };

/** Split an NDJSON byte stream into events, keeping a partial trailing line for the next chunk. */
export function parseNdjson(buffer: string): { events: CompareEvent[]; rest: string } {
  const lines = buffer.split("\n"); const rest = lines.pop() ?? "";
  return { events: lines.filter((l) => l.trim()).map((l) => JSON.parse(l) as CompareEvent), rest };
}

export async function streamCompare(model: string, prompt: string, onEvent: (e: CompareEvent) => void, signal?: AbortSignal): Promise<void> {
  const r = await fetch("/v1/compare/stream", { method: "POST", credentials: "include", signal, headers: { "Content-Type": "application/json", Accept: "application/x-ndjson", ...csrfHeader("POST") }, body: JSON.stringify({ model, prompt }) });
  if (!r.ok || !r.body) { const t = await r.text().catch(() => ""); let msg = `HTTP ${r.status}`; try { msg = JSON.parse(t).error || msg; } catch { /* not JSON */ } throw new Error(msg); }
  const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    buf += dec.decode(value, { stream: !done });
    const { events, rest } = parseNdjson(done ? buf + "\n" : buf); buf = rest;
    events.forEach(onEvent);
    if (done) return;
  }
}

export interface RunResult extends Partial<Metrics> { model: string; response: string; error?: string }
export interface CompareRun { id: string; created_at: number; prompt: string; results: RunResult[]; winner: string | null }
export const loadRuns = () => getJson<{ runs: CompareRun[] }>("/v1/compare/history");
export const saveRun = (prompt: string, results: RunResult[]) => sendJson<CompareRun>("POST", "/v1/compare/history", { prompt, results });
export const voteRun = (id: string, winner: string | null) => sendJson<CompareRun>("PUT", `/v1/compare/history/${id}`, { winner });
export const deleteRun = (id: string) => sendJson("DELETE", `/v1/compare/history/${id}`);
export const fmtCost = (c?: number | null) => (c == null ? "–" : c === 0 ? "$0 (local)" : `$${c.toFixed(4)}`);

// ── Subscription CLIs (no API keys): Codex, Claude Code, Cursor agent, Gemini ──
export interface CliModel { id: string; label: string; context?: number | null }
export interface CliProvider { id: string; label: string; installed: boolean; path: string | null; version: string | null; signed_in: boolean | null; status_note: string; login_command: string; streams: "tokens" | "messages"; models: CliModel[]; enabled: boolean; selected_models: string[]; state: "ready" | "needs-sign-in" | "error" | "not-installed"; last_error?: string | null }
export const loadCliProviders = (refresh = false) => getJson<{ providers: CliProvider[] }>(`/v1/providers/cli${refresh ? "?refresh=1" : ""}`);
export const updateCliProvider = (id: string, body: { enabled?: boolean; models?: string[] }) => sendJson<CliProvider>("PUT", `/v1/providers/cli/${id}`, body);
export const cliModelId = (provider: string, model: string) => `cli:${provider}:${model}`;
/** "cli:codex:gpt-6-luna" → "Codex · gpt-6-luna"; Ollama names pass through. */
export function modelLabel(id: string, providers?: CliProvider[]): string {
  const m = /^cli:([a-z]+):(.+)$/.exec(id);
  if (!m) return id;
  const p = providers?.find((x) => x.id === m[1]);
  return `${p?.label ?? m[1]} · ${p?.models.find((x) => x.id === m[2])?.label ?? m[2]}`;
}
export const CLI_STATE: Record<CliProvider["state"], ["ok" | "warn" | "bad" | undefined, string]> = { ready: ["ok", "Ready"], "needs-sign-in": ["warn", "Needs sign-in"], error: ["bad", "Error"], "not-installed": [undefined, "Not installed"] };
/** Models Compare may run: enabled, installed, not known to need sign-in, and picked in Settings. */
export const runnableCli = (ps: CliProvider[]) => ps.filter((p) => p.enabled && p.installed && p.signed_in !== false).map((p) => ({ provider: p, models: p.models.filter((m) => p.selected_models.includes(m.id)) })).filter((x) => x.models.length);
