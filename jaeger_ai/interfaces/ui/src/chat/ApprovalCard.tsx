import { useRef, useState } from "react";
import { useClarificationAnswers } from "./clarificationAnswers";
/* Approval card in Codex's shape: the exact command, then Deny / Always for this
 * session / Approve once. Esc denies only while focus is inside the card.
 * "Always for this session" is a session grant, not a standing allow-forever. */
import type { KeyboardEvent } from "react";
import { Icon } from "../icons/Icon";
import type { ClarifyAnswerResult } from "./host";

export type ApprovalDecision = "once" | "session" | "deny";

const SHELL_TOOLS = /^(execute_code|run_command|run_terminal|terminal|shell|bash|zsh|sh|exec|command)$/i;

/** The exact thing being approved: the tool's command/code/path input when we have it, else the gateway target. */
export function approvalSubject(input: unknown, message: string): string {
  if (input && typeof input === "object") {
    const i = input as Record<string, unknown>;
    for (const k of ["command", "cmd", "code", "script", "path", "target"]) if (typeof i[k] === "string" && (i[k] as string).trim()) return i[k] as string;
  }
  return message;
}

function settledLabel(decided: "approve" | "deny" | "session"): string {
  if (decided === "deny") return "Denied";
  if (decided === "session") return "Approved for this session";
  return "Approved";
}

export function ApprovalCard({ title, message, toolName, input, decided, reviewerVerdict, reviewerReason, onDecide }: {
  title: string; message: string; toolName?: string; input?: unknown; decided?: "approve" | "deny" | "session";
  reviewerVerdict?: string; reviewerReason?: string;
  onDecide: (decision: ApprovalDecision) => void;
}) {
  const tool = toolName ?? /^Run (.+)\?$/.exec(title)?.[1];
  const shell = Boolean(tool && SHELL_TOOLS.test(tool));
  const heading = /hand.?off/i.test(title) ? title : shell ? "Approve terminal command" : "Approve tool call";
  const subject = approvalSubject(input, message);
  if (decided) {
    const kind = decided === "deny" ? "deny" : "approve";
    return (
      <div className={`jg-approval is-decided is-${kind}`} role="status" data-sender="assistant">
        <Icon name={kind === "approve" ? "check" : "close"} size={14} />
        <span>{settledLabel(decided)}</span>
        <code className="jg-approval__inline">{tool ?? subject}</code>
      </div>
    );
  }
  const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); onDecide("deny"); } };
  return (
    <div className="jg-approval" role="group" aria-label={heading} data-sender="assistant" tabIndex={0} onKeyDown={onKey}>
      <div className="jg-approval__head">
        <Icon name={shell ? "terminal" : "question"} size={15} />
        <span className="jg-approval__title">{heading}</span>
        {tool && <span className="jg-approval__tool">{tool}</span>}
      </div>
      {subject && <pre className="jg-approval__cmd" aria-label="Command">{subject}</pre>}
      {subject !== message && message && <div className="jg-approval__note">{message}</div>}
      {reviewerReason && <div className="jg-approval__review">{reviewerVerdict === "deny" ? "Reviewer declined" : reviewerVerdict === "unsure" ? "Reviewer was unsure" : "Reviewer"}: {reviewerReason}</div>}
      <div className="jg-approval__actions">
        <button type="button" className="jg-action" onClick={() => onDecide("deny")}>Deny <kbd>Esc</kbd></button>
        <button type="button" className="jg-action" onClick={() => onDecide("session")}>Always for this session</button>
        <button type="button" className="jg-action jg-action--primary" onClick={() => onDecide("once")}>Approve once</button>
      </div>
    </div>
  );
}

/** An agent's question, in the approval card's shape: question icon + title, lettered options, the chosen one
 * checked and highlighted, and an "Answered" footer once a choice exists (the gateway records the answer).
 * A pending server clarify form (GB-033) is answerable once: a choice or free text, at its revision. */
export function QuestionCard({ title, options, chosenId, answer: savedAnswer, status: serverStatus, onAnswer, answerKey }: {
  title: string; options: Array<{ id: string; label: string }>; chosenId?: string; answer?: string | null;
  status?: "pending" | "answered" | "cancelled" | "expired"; onAnswer?: (response: string) => Promise<void | ClarifyAnswerResult>; answerKey?: string;
}) {
  const answers = useClarificationAnswers();
  const acknowledged = answerKey ? answers?.outcomes[answerKey] : undefined;
  const status = acknowledged?.status ?? serverStatus;
  if (acknowledged?.status === "answered") savedAnswer = acknowledged.answer;
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState<string>();
  const [resolved, setResolved] = useState<"cancelled" | "expired">();
  const open = status === "pending" && resolved === undefined && Boolean(onAnswer) && sent === undefined;
  const lock = useRef(false);  // synchronous: two clicks in one frame must not send twice
  const answer = async (response: string) => {
    const value = response.trim();
    if (!open || lock.current || !value || !onAnswer) return;
    lock.current = true; setBusy(true); setError("");
    try {
      const result = await onAnswer(value);
      if (answerKey) answers?.record(answerKey, result ?? { status: "answered", answer: value });
      if (result?.status === "cancelled" || result?.status === "expired") setResolved(result.status);
      else setSent(result?.status === "answered" && typeof result.answer === "string" ? result.answer : value);
    }
    catch (e) { setError(String((e as Error)?.message ?? e)); }
    finally { lock.current = false; setBusy(false); }
  };
  const chosenLabel = sent ?? savedAnswer ?? options.find((o) => o.id === chosenId)?.label;
  const finalStatus = resolved ?? status;
  const foot = sent !== undefined || finalStatus === "answered" || chosenId ? "Answered"
    : finalStatus === "expired" ? "Expired: the bot continued without an answer"
    : finalStatus === "cancelled" ? "Cancelled" : "";
  return (
    <div className="jg-approval jg-question" role="group" aria-label={title} data-sender="assistant">
      <div className="jg-approval__head"><Icon name="question" size={15} /><span className="jg-approval__title">{title}</span></div>
      <ul className="jg-question__options">
        {options.map((o, i) => {
          const chosen = o.id === chosenId || (savedAnswer !== undefined && savedAnswer !== null && o.label === savedAnswer) || (sent !== undefined && o.label === sent);
          const inner = <><span className="jg-question__key">{String.fromCharCode(65 + i)}</span>
            <span className="jg-question__label">{o.label}</span>
            {chosen && <Icon name="check" size={14} className="jg-question__check" />}</>;
          return (
            <li key={o.id} className={`jg-question__option${chosen ? " is-chosen" : ""}`} aria-current={chosen ? "true" : undefined}>
              {open ? <button type="button" className="jg-question__pick" disabled={busy} onClick={() => void answer(o.label)}>{inner}</button> : inner}
            </li>
          );
        })}
      </ul>
      {open && <form className="jg-question__free" onSubmit={(e) => { e.preventDefault(); void answer(text); }}>
        <input aria-label="Your answer" value={text} disabled={busy} maxLength={4000} onChange={(e) => setText(e.target.value)} />
        <button type="submit" disabled={busy || !text.trim()}>Answer</button>
      </form>}
      {error && <p role="alert" className="jg-question__error">{error}</p>}
      {foot && <div className="jg-question__foot">{foot}{chosenLabel && !chosenId && (sent !== undefined || savedAnswer != null) ? `: ${chosenLabel}` : ""}</div>}
    </div>
  );
}
