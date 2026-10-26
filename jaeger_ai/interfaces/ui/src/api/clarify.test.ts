import { expect, it, vi } from "vitest";
import { GatewayClient } from "./gateway";
import type { JaegerSource } from "./source";
import { WebHost } from "../chat/webHost";

it("loads clarification history for the exact encoded session", async () => {
  const client = new GatewayClient();
  const request = vi.spyOn(client, "json").mockResolvedValue({ forms: [] });
  expect(await client.clarifications("session/one")).toEqual([]);
  expect(request).toHaveBeenCalledWith("/v1/sessions/session%2Fone/clarify?include_resolved=true");
});

it("looks up one original clarification by encoded session and form IDs", async () => {
  const client = new GatewayClient();
  const form = { clarify_id: "q/1", session_id: "s/1", request_id: "r1", question: "Q", choices: [], revision: 2, status: "answered", answer: "A" };
  const request = vi.spyOn(client, "json").mockResolvedValue({ form });
  expect(await client.clarificationStatus("s/1", "q/1")).toEqual(form);
  expect(request).toHaveBeenCalledWith("/v1/sessions/s%2F1/clarify?clarify_id=q%2F1");
});

it("reconciles a lost answer acknowledgement by reading the same form, never resending", async () => {
  const answerClarify = vi.fn().mockRejectedValue(new Error("connection closed"));
  const clarificationStatus = vi.fn().mockResolvedValue({ clarify_id: "q1", session_id: "s1", request_id: "r1", question: "Q", choices: [], revision: 4, status: "answered", answer: "saved answer" });
  const host = new WebHost({ answerClarify, clarificationStatus } as unknown as JaegerSource);
  await expect(host.answerClarify!("s1", "q1", 4, "requested answer")).resolves.toEqual({ status: "answered", answer: "saved answer" });
  expect(answerClarify).toHaveBeenCalledTimes(1);
  expect(answerClarify).toHaveBeenCalledWith("s1", "q1", 4, "requested answer");
  expect(clarificationStatus).toHaveBeenCalledTimes(1);
  expect(clarificationStatus).toHaveBeenCalledWith("s1", "q1");
});

it("keeps an unanswered original form unknown after a lost acknowledgement", async () => {
  const answerClarify = vi.fn().mockRejectedValue(new Error("connection closed"));
  const clarificationStatus = vi.fn().mockResolvedValue({ clarify_id: "q1", session_id: "s1", request_id: "r1", question: "Q", choices: [], revision: 4, status: "pending", answer: null });
  const host = new WebHost({ answerClarify, clarificationStatus } as unknown as JaegerSource);
  await expect(host.answerClarify!("s1", "q1", 4, "answer")).rejects.toThrow("connection closed");
  expect(answerClarify).toHaveBeenCalledTimes(1);
  expect(clarificationStatus).toHaveBeenCalledTimes(1);
});

it("does not report an unsupported clarification source as an empty history", async () => {
  const host = new WebHost({} as JaegerSource);
  await expect(host.clarifications("s1")).rejects.toThrow("Clarification history is unavailable");
});