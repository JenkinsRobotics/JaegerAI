/* GB-033 client: server clarify forms map to one answerable card, answered exactly once (isolated fixtures). */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { QuestionCard } from "./ApprovalCard";
import { mapEvent } from "./eventMap";
import { applyPart, type ChatPart } from "./host";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

it("maps clarify.request/resolved to one question part whose status updates in place", () => {
  const req = mapEvent({ event: "clarify.request", payload: { clarify_id: "q1", revision: 1, question: "Staging or prod?", choices: ["staging", "prod"], session_id: "s1" } } as never)!;
  let parts: ChatPart[] = applyPart([], req.parts[0]);
  expect(parts[0]).toMatchObject({ kind: "question", callId: "q1", status: "pending", revision: 1, title: "Staging or prod?" });
  parts = applyPart(parts, mapEvent({ event: "clarify.request", payload: { clarify_id: "q1", revision: 1, question: "Staging or prod?", choices: ["staging", "prod"] } } as never)!.parts[0]);
  expect(parts).toHaveLength(1);                                   // replayed SSE: still one card
  parts = applyPart(parts, mapEvent({ event: "clarify.resolved", payload: { clarify_id: "q1", status: "answered" } } as never)!.parts[0]);
  expect(parts).toHaveLength(1);
  expect(parts[0]).toMatchObject({ status: "answered", title: "Staging or prod?" });
  expect((parts[0] as Extract<ChatPart, { kind: "question" }>).options.map((o) => o.label)).toEqual(["staging", "prod"]);
});

it("answers once with a choice; a rejected answer (409) keeps the card open with the reason", async () => {
  const el = document.createElement("div"); document.body.append(el); const root = createRoot(el);
  const onAnswer = vi.fn().mockRejectedValueOnce(new Error("Stale clarify revision")).mockResolvedValueOnce(undefined);
  await act(async () => root.render(<QuestionCard title="Staging or prod?" options={[{ id: "c0", label: "staging" }, { id: "c1", label: "prod" }]} status="pending" onAnswer={onAnswer} />));
  const pick = () => el.querySelector<HTMLButtonElement>(".jg-question__pick")!;
  await act(async () => pick().click()); await flush();
  expect(el.querySelector('[role="alert"]')?.textContent).toBe("Stale clarify revision");
  expect(pick()).toBeTruthy();
  await act(async () => { pick().click(); pick().click(); }); await flush();
  expect(onAnswer).toHaveBeenCalledTimes(2);
  expect(onAnswer).toHaveBeenLastCalledWith("staging");
  expect(el.querySelector(".jg-question__pick")).toBeNull();     // resolved: no further answers
  expect(el.textContent).toContain("Answered");
  act(() => root.unmount()); el.remove();
});

it("free text answers, whitespace cannot, and resolved or display-only cards have no controls", async () => {
  const el = document.createElement("div"); document.body.append(el); const root = createRoot(el);
  const onAnswer = vi.fn().mockResolvedValue(undefined);
  await act(async () => root.render(<QuestionCard title="Name?" options={[]} status="pending" onAnswer={onAnswer} />));
  const input = el.querySelector<HTMLInputElement>('input[aria-label="Your answer"]')!;
  const submit = el.querySelector<HTMLButtonElement>('.jg-question__free button[type="submit"]')!;
  const set = (v: string) => act(() => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, v); input.dispatchEvent(new Event("input", { bubbles: true })); });
  set("   ");
  expect(submit.disabled).toBe(true);
  set("Rex");
  await act(async () => submit.click()); await flush();
  expect(onAnswer).toHaveBeenCalledWith("Rex");
  await act(async () => root.render(<QuestionCard key="fresh" title="Name?" options={[]} status="expired" onAnswer={onAnswer} />));
  expect(el.querySelector("input")).toBeNull();
  expect(el.textContent).toContain("Expired");
  await act(async () => root.render(<QuestionCard title="Q" options={[{ id: "a", label: "A" }]} chosenId="a" />));
  expect(el.querySelector("button")).toBeNull();
  act(() => root.unmount()); el.remove();
});
