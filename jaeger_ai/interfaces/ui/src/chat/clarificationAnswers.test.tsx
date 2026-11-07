import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { QuestionCard } from "./ApprovalCard";
import { ClarificationAnswers, clarificationAnswerKey } from "./clarificationAnswers";

it("retains the server acknowledgement when an in-flight answer changes renderer", async () => {
  let acknowledge!: (value: { status: "answered"; answer: string }) => void;
  const onAnswer = vi.fn(() => new Promise<{ status: "answered"; answer: string }>(resolve => { acknowledge = resolve; }));
  const el = document.createElement("div"); document.body.append(el); const root = createRoot(el);
  const render = (renderer: string, session = "s1") => <ClarificationAnswers key={session}><QuestionCard key={renderer} title="Which environment?" options={[{ id: "staging", label: "staging" }]} status="pending" answerKey={clarificationAnswerKey("q1", 1)} onAnswer={onAnswer} /></ClarificationAnswers>;
  await act(async () => root.render(render("restored")));
  await act(async () => el.querySelector<HTMLButtonElement>(".jg-question__pick")!.click());
  await act(async () => root.render(render("transcript")));
  await act(async () => acknowledge({ status: "answered", answer: "staging" }));
  expect(el.textContent).toContain("Answered: staging");
  expect(el.querySelector("input")).toBeNull();
  await act(async () => root.render(render("restored")));
  expect(el.textContent).toContain("Answered: staging");
  expect(onAnswer).toHaveBeenCalledTimes(1);
  await act(async () => root.render(render("restored", "another-session")));
  expect(el.textContent).not.toContain("Answered");
  expect(el.querySelector("input")).not.toBeNull();
  act(() => root.unmount()); el.remove();
});
