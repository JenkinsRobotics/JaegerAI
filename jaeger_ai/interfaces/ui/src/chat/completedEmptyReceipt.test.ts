import { describe, expect, it } from "vitest";
import type { GatewayEvent } from "../api/types";
import { mapEvent } from "./eventMap";
import { applyPart, type ChatPart } from "./host";
import { requestOutcome } from "./requestOutcome";

const observed = (): ChatPart[] => [
  {kind: "markdownContent", text: "Checking.", role: "commentary"},
  {kind: "markdownContent", text: "Provisional"},
  {kind: "markdownContent", text: "Streamed final", role: "final", itemId: "message-1"},
];
const completedEmpty: ChatPart = {kind: "markdownContent", text: "", role: "final", itemId: "final", authoritativeEmpty: true};

describe("completed-empty receipts after stream reconciliation", () => {
  it.each(["durable", "reconciled"])("%s receipt clears answer text, preserves commentary, and is idempotent", source => {
    let parts = observed();
    const apply = (part: ChatPart) => { parts = applyPart(parts, part); };
    const settle = () => {
      if (source === "durable") requestOutcome({status: "completed", result: {output: ""}}, apply);
      else mapEvent({event: "turn.reconciled", payload: {status: "completed", output: ""}} as GatewayEvent)!.parts.forEach(apply);
    };
    settle();
    const expected = [observed()[0], completedEmpty];
    expect(parts).toEqual(expected);
    settle();
    expect(parts).toEqual(expected);
  });

  it("ignores empty stream deltas even when they use final role and identity", () => {
    const parts = observed();
    const mapped = mapEvent({event: "turn.delta", payload: {delta: "", channel: "final", item_id: "final", authoritativeEmpty: true}} as GatewayEvent)!;
    expect(mapped.parts.reduce(applyPart, parts)).toEqual(parts);
  });

  it.each([undefined, null, 0, {}, []])("does not treat absent or nonstring output %j as an empty receipt", output => {
    let parts = observed();
    // Exercise malformed transport values beyond the compile-time contract.
    requestOutcome({status: "completed", result: {output: output as unknown as string | undefined}}, part => { parts = applyPart(parts, part); });
    expect(parts).toEqual(observed());
  });

  it.each(["failed", "cancelled", "execution_unknown"])("%s empty receipt preserves all observed text", status => {
    let parts = observed();
    requestOutcome({status, result: {output: ""}}, part => { parts = applyPart(parts, part); });
    expect(parts.filter(part => part.kind === "markdownContent")).toEqual(observed());
  });

  it.each([{role: "provisional" as const, itemId: "final"}, {role: "final" as const, itemId: "stream"}])("rejects an empty marker without canonical receipt identity %j", identity => {
    expect(applyPart(observed(), {...completedEmpty, ...identity} as ChatPart)).toEqual(observed());
  });
});
