import { beforeEach, expect, it } from "vitest";
import type { JaegerSource } from "../api/source";
import type { GatewayEvent } from "../api/types";
import { applyPart, type ChatPart } from "./host";
import { WebHost } from "./webHost";

beforeEach(() => localStorage.clear());

async function runRace(delay: number, childIds: string[] = []) {
  let emit!: (event: GatewayEvent) => void;
  let acknowledge!: (receipt: Awaited<ReturnType<JaegerSource["cancel"]>>) => void;
  let parts: ChatPart[] = [];
  const source = {
    send: async () => ({request_id: "r", start_event_id: 1}),
    cancel: () => new Promise(resolve => { acknowledge = resolve; }),
    stream: async (_session: string, _cursor: number, onEvent: (event: GatewayEvent) => void, signal: AbortSignal) => {
      emit = onEvent;
      await new Promise<void>(resolve => signal.addEventListener("abort", () => resolve(), {once: true}));
    },
  } as unknown as JaegerSource;
  const handle = new WebHost(source).startTurn({sessionId: "s", turnId: "r", message: "race"}, part => { parts = applyPart(parts, part); });
  for (let i = 0; !emit && i < 100; i++) await Promise.resolve();
  expect(emit).toBeTypeOf("function");
  handle.cancel();
  emit({event_id: 2, event: "turn.cancelled", request_id: "r", payload: {}});
  const ackDone = new Promise<void>(resolve => {
    const settle = (remaining: number) => remaining
      ? queueMicrotask(() => settle(remaining - 1))
      : (acknowledge({request_id: "r", session_id: "s", status: "cancelling", cancel_requested: true, cancellation_confirmed: false, unconfirmed_task_ids: childIds}), resolve());
    settle(delay);
  });
  expect((await handle.done).state).toBe("cancelled");
  await ackDone;
  await Promise.resolve();
  return parts.filter(part => part.kind === "warning");
}

it.each(Array.from({length: 20}, (_, i) => i))("a cancel acknowledgment delayed %i microtasks cannot reopen the settled Stop notice", async delay => {
  expect(await runRace(delay)).toEqual([{kind: "warning", noticeId: "stop", message: "Stopped. The Gateway confirmed this request was cancelled."}]);
});

it("keeps late unconfirmed owned-work IDs visible without reopening parent Stop", async () => {
  const warnings = await runRace(8, ["owned-child"]);
  expect(warnings.find(part => part.noticeId === "stop")?.message).toBe("Stopped. The Gateway confirmed this request was cancelled.");
  expect(warnings.some(part => part.message.includes("owned-child") && part.message.includes("unconfirmed"))).toBe(true);
  expect(warnings.some(part => part.message.includes("waiting for the Gateway"))).toBe(false);
});
