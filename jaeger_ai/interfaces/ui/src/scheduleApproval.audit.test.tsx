import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { JaegerApp } from "@jaeger/ui-features";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows a persisted schedule proposal after reconnect and submits the owner decision", async () => {
  window.localStorage.clear();
  window.history.pushState(null, "", "/");
  let pending = true;
  const sessionId = "sess_jaeger_chat";
  const decisions: unknown[] = [];
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/v1/chat/session")) return Response.json({ session: { session_id: sessionId } });
    if (url.includes("/messages")) return Response.json({ messages: [], has_older: false, after_seq: 0 });
    if (url.includes("/events")) return new Response(new ReadableStream({}), { status: 200 });
    if (url.includes("/v1/approvals/apr-schedule-fixture/resolve")) {
      decisions.push(JSON.parse(String(init?.body)));
      if (decisions.length === 1) return Response.json({ ok: false }, { status: 409 });
      pending = false;
      return Response.json({ ok: true });
    }
    if (url.includes("/v1/approvals?session_id=")) {
      return Response.json({
        approvals: pending ? [{
          approval_id: "apr-schedule-fixture",
          tool_name: "schedule-proposal",
          session_id: sessionId,
          status: "pending",
          prompt: JSON.stringify({ prompt: "Summarize tonight's fixture", due_at: 1800000000, interval_s: 300 }),
        }] : [],
      });
    }
    return Response.json({ sessions: [], tools: [], workflows: [], facts: [], models: [], all_green: true });
  });
  vi.stubGlobal("fetch", fetcher);

  render(<JaegerApp />);
  const proposal = await screen.findByTestId("approval-card-apr-schedule-fixture");
  expect(proposal).toHaveTextContent("Summarize tonight's fixture");
  fireEvent.click(screen.getByRole("button", { name: "Approve" }));
  await waitFor(() => expect(decisions).toEqual([{ decision: "approve" }]));
  expect(await screen.findByText("Could not record the approval decision.")).toBeVisible();
  expect(screen.getByTestId("approval-card-apr-schedule-fixture")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Approve" }));
  await waitFor(() => expect(decisions).toHaveLength(2));
  await waitFor(() => expect(screen.queryByTestId("approval-card-apr-schedule-fixture")).toBeNull());
});
