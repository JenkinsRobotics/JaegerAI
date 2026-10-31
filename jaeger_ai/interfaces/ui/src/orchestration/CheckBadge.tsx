import { Badge } from "../unified/ui";
import type { HandoffCheck } from "./types";

const TEXT = { passed: "Checked", failed: "Check failed", pending: "Checking", unchecked: "Not checked" } as const;
const TONE = { passed: "ok", failed: "bad", pending: "warn", unchecked: undefined } as const;

/** Result-check pill. "derived" checks say so, so a task state is never
 * passed off as a reviewer's verdict. */
export function CheckBadge({ check }: { check: HandoffCheck }) {
  const title = check.source === "derived" ? "From the linked task's state" : check.checkedBy ? `Checked by ${check.checkedBy}` : "Gateway check";
  return <span className="jg-orch-check" title={title} data-state={check.state}><Badge tone={TONE[check.state]}>{TEXT[check.state]}{check.source === "derived" && check.state !== "unchecked" ? " · task" : ""}</Badge></span>;
}
