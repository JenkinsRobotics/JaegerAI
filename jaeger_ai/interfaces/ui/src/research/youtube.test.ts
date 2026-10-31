import { describe, expect, it } from "vitest";
import { evidence, filterVideos, fmtTime, framePath, jobState, pct, videoRollup, type YtVideoRow } from "./youtube";

const done = { status: "done" };
const row = (id: string, steps: Record<string, { status: string }>, title = id): YtVideoRow => ({ id, title, steps });
const all = Object.fromEntries(["meta", "transcript", "frames", "ocr", "audio", "shot_notes", "timeline", "analysis"].map((k) => [k, done]));

describe("youtube research helpers", () => {
  it("formats times and progress", () => {
    expect(fmtTime(65)).toBe("1:05"); expect(fmtTime(3725)).toBe("1:02:05"); expect(fmtTime(undefined)).toBe("–");
    expect(pct({ steps_finished: 205, steps_total: 320 })).toBe(64); expect(pct(undefined)).toBe(0);
  });
  it("rolls up a video's steps: analysed, next step, or first failure", () => {
    expect(videoRollup(row("a", all))).toMatchObject({ done: 8, label: "Analysed", tone: "ok" });
    expect(videoRollup(row("b", { meta: done, transcript: done }))).toMatchObject({ done: 2, label: "Frames next" });
    expect(videoRollup(row("c", { meta: done, transcript: { status: "failed" } }))).toMatchObject({ failed: "transcript", tone: "bad" });
  });
  it("filters by text and state", () => {
    const rows = [row("a", all, "Build log"), row("b", { meta: done }, "Teaser"), row("c", { meta: { status: "failed" } }, "Broken")];
    expect(filterVideos(rows, "build", "all").map((r) => r.id)).toEqual(["a"]);
    expect(filterVideos(rows, "", "done").map((r) => r.id)).toEqual(["a"]);
    expect(filterVideos(rows, "", "pending").map((r) => r.id)).toEqual(["b"]);
    expect(filterVideos(rows, "", "failed").map((r) => r.id)).toEqual(["c"]);
  });
  it("labels job state with paused winning over running", () => {
    expect(jobState({ task_id: "x", running: true, paused: true }).label).toBe("Paused");
    expect(jobState({ task_id: "x", running: true, progress: { steps_finished: 1, steps_total: 4 } }).label).toBe("Running 25%");
  });
  it("orders evidence by time and builds encoded frame URLs the API serves", () => {
    const ev = evidence({ video: row("v", {}), shot_notes: { notes: [{ t: 30, note: "cut" }] }, ocr_spans: [{ t: 5, text: "SUBSCRIBE" }] });
    expect(ev.map((e) => e.kind)).toEqual(["text", "note"]);
    expect(framePath("yt:PL1", "DQJ3F4ZOkzk", "frames/f000.jpg")).toBe("/v1/research/youtube/yt%3APL1/videos/DQJ3F4ZOkzk/frames/f000.jpg");
  });
});
