/**
 * Task pipeline: Intake → Research → Studio → Production → Review → Done.
 * Stage + attachments are persisted by the WebUI (/v1/pipeline, <state>/pipeline/tasks.json) keyed by
 * the gateway task_id — the gateway's task schema has no writable stage field. Stages only change on an
 * explicit user action; the gateway's own task state (running/succeeded/…) is shown separately.
 */
import { getJson, sendJson } from "./webui";

export const STAGES = ["intake", "research", "studio", "production", "review", "done"] as const;
export type Stage = (typeof STAGES)[number];
export const STAGE_LABEL: Record<Stage, string> = { intake: "Plan", research: "Research", studio: "Studio", production: "Production", review: "Review", done: "Done" };
export type AttachKind = "note" | "source" | "document" | "asset" | "artifact" | "deliverable";
export interface Attachment { id: string; kind: AttachKind; ref: string | null; label: string | null; text: string | null; stage: Stage; at: number }
export interface PipelineRecord { task_id: string; stage: Stage | null; revision: number; history: { from: Stage | null; to: Stage; at: number; note: string | null }[]; attachments: Attachment[]; updated_at?: number }

export const nextStage = (s: Stage | null): Stage | null => (s === null ? "intake" : STAGES[STAGES.indexOf(s) + 1] ?? null);

/** Where a stage's work happens; the task travels along as ?task=. */
export function stagePath(stage: Stage, taskId: string): string {
  const q = `?task=${encodeURIComponent(taskId)}`;
  switch (stage) {
    case "research": return `/research${q}`;
    case "studio": return `/studio${q}`;
    case "production": return `/work/production${q}`;
    default: return `/work${q}`;
  }
}

export const pipelineApi = {
  list: () => getJson<{ stages: Stage[]; items: Record<string, PipelineRecord> }>("/v1/pipeline"),
  setStage: (taskId: string, stage: Stage, expected_revision?: number) => sendJson<PipelineRecord>("PUT", `/v1/pipeline/${encodeURIComponent(taskId)}`, { stage, expected_revision }),
  attach: (taskId: string, a: { kind: AttachKind; ref?: string; label?: string; text?: string }) => sendJson<Attachment>("POST", `/v1/pipeline/${encodeURIComponent(taskId)}/attachments`, a),
  detach: (taskId: string, id: string) => sendJson<{ deleted: string }>("DELETE", `/v1/pipeline/${encodeURIComponent(taskId)}/attachments/${id}`),
};
