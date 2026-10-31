/** YouTube research (GET /v1/research/youtube…): types and pure helpers for the Research › YouTube sub-tab. */
export type StepState = { status: "done" | "pending" | "running" | "failed" | "skipped" | string; error?: string | null; at?: number; count?: number; model?: string; lufs?: number; with_text?: number; cuts?: number; source?: string };
export const STEP_ORDER = ["meta", "transcript", "frames", "ocr", "audio", "shot_notes", "timeline", "analysis"] as const;
export const STEP_LABEL: Record<string, string> = { meta: "Metadata", transcript: "Transcript", frames: "Frames", ocr: "On-screen text", audio: "Audio", shot_notes: "Shot notes", timeline: "Timeline", analysis: "Analysis" };
export type YtVideoRow = { id: string; title: string; duration?: number; channel?: string; url?: string; position?: number; steps?: Record<string, StepState> };
export type YtProgress = { steps_finished: number; steps_total: number; videos_analysed?: number; videos_with_errors?: number; videos?: number };
export type YtJobSummary = { task_id: string; playlist_title?: string; playlist_url?: string; state?: string; phase?: number; running?: boolean; paused?: boolean; progress?: YtProgress; updated_at?: number; style_guide?: string };
export type YtJob = YtJobSummary & { item_count?: number; channel?: string; model?: string; video_model?: string; videos: YtVideoRow[]; kb?: { status?: string; [k: string]: unknown }; error?: string | null };
export type YtFrame = { file: string; t: number; kind?: string };
export type YtVideo = {
  video: YtVideoRow; meta?: { title?: string; duration?: number; view_count?: number; chapters?: { title: string; start_time: number }[]; [k: string]: unknown };
  transcript?: { segments?: { start: number; text: string }[]; source?: string } | null;
  frames?: YtFrame[]; cut_list?: { t: number; shot_len_s?: number }[]; ocr_spans?: { t: number; t_end?: number; text: string }[];
  audio?: { lufs?: number; [k: string]: unknown } | null; shot_notes?: { model?: string; notes: { t: number; note: string }[] } | null;
  analysis?: { summary?: string; scores?: Record<string, number>; [k: string]: unknown } | null;
};
export type Technique = { id?: string; name?: string; type?: string; summary?: string; videos?: string[]; count?: number };

export const ytBase = "/v1/research/youtube";
export const jobPath = (id: string) => `${ytBase}/${encodeURIComponent(id)}`;
export const videoPath = (job: string, vid: string) => `${jobPath(job)}/videos/${encodeURIComponent(vid)}`;
export const framePath = (job: string, vid: string, file: string) => `${videoPath(job, vid)}/${file.replace(/^\/+/, "")}`;

export function fmtTime(s: number | undefined): string {
  if (s == null || !Number.isFinite(s)) return "–";
  const t = Math.max(0, Math.floor(s)); const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), sec = t % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}

export function pct(p?: YtProgress): number { return p && p.steps_total ? Math.min(100, Math.floor((p.steps_finished / p.steps_total) * 100)) : 0; }

/** Per-video rollup: how many pipeline steps are done, and the first failure if any. */
export function videoRollup(v: YtVideoRow): { done: number; total: number; failed?: string; label: string; tone: "ok" | "warn" | "bad" | undefined } {
  const steps = v.steps ?? {}; const total = STEP_ORDER.length;
  const done = STEP_ORDER.filter((k) => steps[k]?.status === "done").length;
  const failedKey = STEP_ORDER.find((k) => steps[k]?.status === "failed");
  if (failedKey) return { done, total, failed: failedKey, label: `${STEP_LABEL[failedKey]} failed`, tone: "bad" };
  if (done === total) return { done, total, label: "Analysed", tone: "ok" };
  const next = STEP_ORDER.find((k) => steps[k]?.status !== "done");
  return { done, total, label: next ? `${STEP_LABEL[next]} next` : "Queued", tone: done ? "warn" : undefined };
}

export function jobState(j: YtJobSummary): { label: string; tone: "ok" | "warn" | "bad" | undefined } {
  if (j.paused) return { label: "Paused", tone: "warn" };
  if (j.state === "failed") return { label: "Failed", tone: "bad" };
  if (j.running || j.state === "running") return { label: `Running ${pct(j.progress)}%`, tone: undefined };
  if (j.state === "done" || j.state === "complete") return { label: "Done", tone: "ok" };
  return { label: j.state ? j.state[0].toUpperCase() + j.state.slice(1) : "Idle", tone: undefined };
}

/** Merge shot notes, OCR spans and cuts into one time-ordered evidence list for the video inspector. */
export function evidence(v: YtVideo): { t: number; kind: "note" | "text" | "cut"; text: string }[] {
  const out: { t: number; kind: "note" | "text" | "cut"; text: string }[] = [];
  for (const n of v.shot_notes?.notes ?? []) out.push({ t: n.t, kind: "note", text: n.note });
  for (const o of v.ocr_spans ?? []) out.push({ t: o.t, kind: "text", text: o.text });
  return out.sort((a, b) => a.t - b.t);
}

export function filterVideos(rows: YtVideoRow[], q: string, only: "all" | "done" | "failed" | "pending"): YtVideoRow[] {
  const needle = q.trim().toLowerCase();
  return rows.filter((v) => {
    if (needle && !(`${v.title} ${v.channel ?? ""}`.toLowerCase().includes(needle))) return false;
    const r = videoRollup(v);
    if (only === "done") return r.done === r.total;
    if (only === "failed") return !!r.failed;
    if (only === "pending") return !r.failed && r.done < r.total;
    return true;
  });
}
