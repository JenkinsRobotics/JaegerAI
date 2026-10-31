import { Badge } from "../unified/ui";
import type { HandoffCheck } from "./types";

const TEXT = { passed: "Checked", failed: "Check failed", pending: "Checking", unchecked: "Not checked" } as const;
const TONE = { passed: "ok", failed: "bad", pending: "warn", unchecked: undefined } as const;

/** Result-check pill. "derived" checks say so, so a task state is never
 * passed off as a reviewer's verdict. */
export function CheckBadge({ check }: { check: HandoffCheck }) {
  const fromTask = check.evidence?.kind === "task";
  const title = check.source === "derived" ? (fromTask ? "From the linked task's state" : "From the handoff's status (no reviewer check yet)") : check.checkedBy ? `Checked by ${check.checkedBy}` : "Gateway check";
  const suffix = check.source === "derived" && check.state !== "unchecked" ? (fromTask ? " · task" : " · status") : "";
  return <span className="jg-orch-check" title={title} data-state={check.state}><Badge tone={TONE[check.state]}>{TEXT[check.state]}{suffix}</Badge></span>;
}
