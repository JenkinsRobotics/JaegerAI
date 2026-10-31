import { fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Handoff } from "../api/types";
import { gatewayActivity } from "./adapter";
import { activityItemRow, artifactsFor, checkFor, eventRow, parseEvidence, statusTone } from "./feed";
import { mockAdapter, mockFrames, mockSnapshotData } from "./mockOrchestration";
import { OutputLinkView } from "./OutputLinkView";
import { useOrchestration } from "./useOrchestration";

const names = (id: string) => id;

describe("gateway G1–G6 shapes", () => {
  it("#2 parses prefixed evidence_ref", () => {
    expect(parseEvidence("task:T1")).toMatchObject({ kind: "task", href: "/work/tasks?task=T1" });
    expect(parseEvidence("handoff:h1")).toMatchObject({ href: "handoff:h1" });
    expect(parseEvidence("url:https://ci/1")).toMatchObject({ href: "https://ci/1" });
    expect(parseEvidence("url:https://ci/1")?.copy).toBeFalsy();
    expect(parseEvidence("url:http://x/1")).toMatchObject({ copy: true });
    expect(parseEvidence("file:src/a.ts@abc")).toMatchObject({ kind: "file", href: "src/a.ts", sha: "abc", copy: true, label: "a.ts" });
    expect(parseEvidence(null)).toBeUndefined();
  });

  it("#4 gateway check wins, with note", () => {
    const [build, review, research] = mockSnapshotData(1000).handoffs;
    expect(checkFor(build, mockSnapshotData(1000).tasks)).toMatchObject({ state: "unchecked", source: "gateway" });
    expect(checkFor(review, [])).toMatchObject({ state: "passed", note: "tests green", checkedBy: "owner:matthew" });
    expect(checkFor(research, []).evidence?.href).toBe("handoff:h-research");
  });

  it("#5/#6 artifacts: session routes, https url links, file/commit/http chips, verified", () => {
    const out = artifactsFor(mockSnapshotData(1000).handoffs[1]);
    expect(out[0]).toMatchObject({ kind: "session", href: "/chat?agent=native%3Areviewer", verified: true });
    expect(out[1]).toMatchObject({ kind: "commit", href: expect.stringMatching(/^https:\/\/github/) });
    expect(out[2]).toMatchObject({ kind: "file", copy: true, sha: "4be1c0ffee" });
    expect(out[3]).toMatchObject({ kind: "url", copy: true, verified: false });
    const bare = artifactsFor({ id: "x", result: { artifact_refs: [{ kind: "commit", ref: "abcdef1234" }] } } as unknown as Handoff);
    expect(bare[0]).toMatchObject({ copy: true, label: "abcdef12" });
  });

  it("#3 checked event uses the handoff envelope; #7 status time from payload.at; #8 vocabulary", () => {
    const [status, checked] = mockFrames(5000);
    expect(eventRow(checked, names)).toMatchObject({ kind: "handoff.checked", handoffId: "h-build", check: { state: "pending", note: "waiting on CI" }, output: { kind: "task" } });
    expect(eventRow({ event: "agent.handoff.checked", payload: { handoff_id: "h", state: "passed" } }, names)).toBeNull();
    expect(eventRow(status, names)).toMatchObject({ at: 4940, action: "is working", handoffId: "h-build" });
    expect(["working", "waiting_approval", "blocked", "error", "queued", "idle"].map(statusTone)).toEqual(["ok", "warn", "warn", "bad", "idle", "idle"]);
  });

  it("#1 maps G1 items and pages with before/next_before", async () => {
    expect(activityItemRow({ event_id: 1, kind: "project.checked", ts: 10, agent_id: "a", summary: "did it", refs: { task_id: "t" } }, names)).toMatchObject({ action: "did it", output: { kind: "task" } });
    expect(activityItemRow({ event_id: 2, kind: "approval.request", ts: 10, agent_id: "a", needs_me: false, data: { approval_id: "z" } }, names)?.needsYou).toBe(true);
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ items: [], has_more: false, next_before: null })));
    await gatewayActivity("", fetchImpl as unknown as typeof fetch)({ before: 81200, names });
    expect(fetchImpl).toHaveBeenCalledWith("/v1/activity?limit=50&before=81200", expect.anything());
    const missing = vi.fn(async () => new Response("{}", { status: 404 }));
    expect(await gatewayActivity("", missing as unknown as typeof fetch)({ names })).toEqual({ rows: [] });
    const broken = vi.fn(async () => new Response("{}", { status: 500 }));
    await expect(gatewayActivity("", broken as unknown as typeof fetch)({ names })).rejects.toThrow("activity 500");
    const adapter = mockAdapter();
    const { result } = renderHook(() => useOrchestration(adapter));
    await waitFor(() => expect(result.current.loadOlder).toBeDefined());
    expect(result.current.rows.some((r) => r.handoffId === "h-art")).toBe(true);
    void result.current.loadOlder!();
    await waitFor(() => expect(result.current.rows.some((r) => r.taskId === "t-old")).toBe(true));
    await waitFor(() => expect(result.current.loadOlder).toBeUndefined());
  });

  it("renders copy chips and refuses non-https external links", async () => {
    const writeText = vi.fn(async () => undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<OutputLinkView link={{ kind: "commit", label: "abc1234", href: "abc1234def", copy: true, verified: true }} onNavigate={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy abc1234" }));
    expect(writeText).toHaveBeenCalledWith("abc1234def");
    const { container } = render(<OutputLinkView link={{ kind: "url", label: "x", href: "http://x" }} onNavigate={() => undefined} />);
    expect(container.innerHTML).toBe("");
  });
});
