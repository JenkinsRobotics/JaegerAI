import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import type { ClarificationSnapshot } from "../api/source";
import { SessionClarifications } from "./SessionClarifications";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it("recovers only this session's pending forms and answers with its original revision once", async () => {
  const forms: ClarificationSnapshot[] = [
    { clarify_id: "q1", session_id: "s1", request_id: "r1", question: "Where?", choices: ["staging", "prod"], revision: 4, status: "pending", answer: null },
    { clarify_id: "q2", session_id: "s2", request_id: "r2", question: "Foreign?", choices: [], revision: 1, status: "pending", answer: null },
  ];
  const host = { clarifications: vi.fn().mockResolvedValue(forms), answerClarify: vi.fn().mockResolvedValue(undefined) };
  const el = document.createElement("div"); document.body.append(el); const root = createRoot(el);
  await act(async () => root.render(<SessionClarifications sessionId="s1" host={host} />));
  expect(host.clarifications).toHaveBeenCalledWith("s1");
  expect(el.textContent).toContain("Where?");
  expect(el.textContent).not.toContain("Foreign?");
  await act(async () => el.querySelector<HTMLButtonElement>(".jg-question__pick")!.click());
  expect(host.answerClarify).toHaveBeenCalledTimes(1);
  expect(host.answerClarify).toHaveBeenCalledWith("s1", "q1", 4, "staging");
  expect(el.textContent).toContain("Answered");
  act(() => root.unmount()); el.remove();
});

it("does not answer forms already represented in the loaded transcript", async () => {
  const form: ClarificationSnapshot = { clarify_id: "q1", session_id: "s1", request_id: "r1", question: "Where?", choices: [], revision: 1, status: "pending", answer: null };
  const host = { clarifications: vi.fn().mockResolvedValue([form]), answerClarify: vi.fn() };
  const el = document.createElement("div"); document.body.append(el); const root = createRoot(el);
  await act(async () => root.render(<SessionClarifications sessionId="s1" host={host} excludeIds={["q1"]} />));
  expect(el.textContent).not.toContain("Where?");
  expect(el.querySelector("input")).toBeNull();
  act(() => root.unmount()); el.remove();
});

it("reconciles a lost answer acknowledgement from the original form without replay", async () => {
  const form: ClarificationSnapshot = { clarify_id: "q1", session_id: "s1", request_id: "r1", question: "Where?", choices: ["staging", "prod"], revision: 4, status: "pending", answer: null };
  const host = {
    clarifications: vi.fn().mockResolvedValue([form]),
    answerClarify: vi.fn().mockResolvedValue({ status: "answered", answer: "prod" }),
  };
  const el = document.createElement("div"); document.body.append(el); const root = createRoot(el);
  await act(async () => root.render(<SessionClarifications sessionId="s1" host={host} />));
  await act(async () => el.querySelectorAll<HTMLButtonElement>(".jg-question__pick")[1].click());
  expect(host.answerClarify).toHaveBeenCalledTimes(1);
  expect(host.answerClarify).toHaveBeenCalledWith("s1", "q1", 4, "prod");
  expect(el.textContent).toContain("Answered: prod");
  expect(el.textContent).not.toContain("Answer not confirmed");
  act(() => root.unmount()); el.remove();
});

it("restores the saved answer and terminal status without answer controls", async () => {
  const forms: ClarificationSnapshot[] = [
    { clarify_id: "q1", session_id: "s1", request_id: "r1", question: "Where?", choices: ["staging", "prod"], revision: 1, status: "answered", answer: "prod" },
    { clarify_id: "q2", session_id: "s1", request_id: "r2", question: "Which?", choices: [], revision: 1, status: "expired", answer: null },
  ];
  const host = { clarifications: vi.fn().mockResolvedValue(forms) };
  const el = document.createElement("div"); document.body.append(el); const root = createRoot(el);
  await act(async () => root.render(<SessionClarifications sessionId="s1" host={host} />));
  expect(el.textContent).toContain("Answered: prod");
  expect(el.textContent).toContain("Expired: the bot continued without an answer");
  expect(el.querySelector("input")).toBeNull();
  expect(el.querySelector(".jg-question__pick")).toBeNull();
  act(() => root.unmount()); el.remove();
});