/* Approval card in Grok's shape (REA catalog: "Approve terminal command" / "Approve tool call", "Allow once",
 * "Deny once (Esc)", "Approved" / "Denied"): a titled card with the EXACT command or target in a code block, then
 * Allow once / Deny once. Nothing is ever approved without an explicit click: there is no auto-approve and no
 * "Always allow" (Jaeger has no allow-list policy). Esc denies only while focus is inside the card. Once decided,
 * the card collapses to one status line (local; the gateway's tool part carries the real outcome). */
import type { KeyboardEvent } from "react";
import { Icon } from "../icons/Icon";

const SHELL_TOOLS = /^(execute_code|run_command|run_terminal|terminal|shell|bash|zsh|sh|exec|command)$/i;

/** The exact thing being approved: the tool's command/code/path input when we have it, else the gateway target. */
export function approvalSubject(input: unknown, message: string): string {
  if (input && typeof input === "object") {
    const i = input as Record<string, unknown>;
    for (const k of ["command", "cmd", "code", "script", "path", "target"]) if (typeof i[k] === "string" && (i[k] as string).trim()) return i[k] as string;
  }
  return message;
}

export function ApprovalCard({ title, message, toolName, input, decided, onDecide }: {
  title: string; message: string; toolName?: string; input?: unknown; decided?: "approve" | "deny";
  onDecide: (decision: "approve" | "deny") => void;
}) {
  const tool = toolName ?? /^Run (.+)\?$/.exec(title)?.[1];
  const shell = Boolean(tool && SHELL_TOOLS.test(tool));
  const heading = shell ? "Approve terminal command" : "Approve tool call";
  const subject = approvalSubject(input, message);
  if (decided) {
    return (
      <div className={`jg-approval is-decided is-${decided}`} role="status" data-sender="assistant">
        <Icon name={decided === "approve" ? "check" : "close"} size={14} />
        <span>{decided === "approve" ? "Approved" : "Denied"}</span>
        <code className="jg-approval__inline">{tool ?? subject}</code>
      </div>
    );
  }
  const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); onDecide("deny"); } };
  return (
    <div className="jg-approval" role="group" aria-label={heading} data-sender="assistant" onKeyDown={onKey}>
      <div className="jg-approval__head">
        <Icon name={shell ? "terminal" : "question"} size={15} />
        <span className="jg-approval__title">{heading}</span>
        {tool && <span className="jg-approval__tool">{tool}</span>}
      </div>
      {subject && <pre className="jg-approval__cmd" aria-label="Exact command">{subject}</pre>}
      {subject !== message && message && <div className="jg-approval__note">{message}</div>}
      <div className="jg-approval__actions">
        <button type="button" className="jg-action" onClick={() => onDecide("deny")}>Deny once <kbd>Esc</kbd></button>
        <button type="button" className="jg-action jg-action--primary" onClick={() => onDecide("approve")}>Allow once</button>
      </div>
    </div>
  );
}
