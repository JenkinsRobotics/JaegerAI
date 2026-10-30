/** Ollama model helpers for Models / Compare / Documents (unified UI). */
import { getJson } from "./webui";

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
