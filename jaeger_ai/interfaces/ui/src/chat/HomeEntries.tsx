import {displayDate} from "../settings/devicePreferences";
/* Home-chat entries that aren't turns: the summary card that stands in for summarized older
 * messages, and handoff / task results posted into the chat as real messages. */
import { useState } from "react";
import { AgentAvatar } from "../agents/AgentAvatar";
import type { HomeEntry } from "./homeSession";
import { Markdown } from "./Markdown";

type Summary = Extract<HomeEntry, { kind: "summary" }>;
type Post = Extract<HomeEntry, { kind: "post" }>;
type Open = { onOpen: (url: string) => void; onCopy: (text: string) => void };

const day = (ms?: number) => (ms ? displayDate(ms, {month: "short", day: "numeric"}) : "");
export function summaryLine(entry: Summary): string {
  const span = entry.fromAt && entry.toAt ? ` · ${day(entry.fromAt)}–${day(entry.toAt)}` : "";
  return `Earlier conversation summarized${entry.count ? ` (${entry.count} messages)` : ""}${span}`;
}

export function SummaryCard({ entry, links, defaultOpen = false }: { entry: Summary; links: Open; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={`jg-summary${open ? " is-open" : ""}`} role="note" data-sender="summary">
      <div className="jg-summary__line">
        <span>{summaryLine(entry)}</span>
        <span aria-hidden="true">·</span>
        <button type="button" className="jg-summary__toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>{open ? "Hide" : "Show"}</button>
      </div>
      {open && <div className="jg-summary__text jg-md"><Markdown text={entry.text} onOpen={links.onOpen} onCopy={links.onCopy} /></div>}
    </div>
  );
}

const STATUS: Record<string, string> = { completed: "Completed", pending_approval: "Awaiting approval", admitted: "Queued", running: "Working", execution_unknown: "Outcome unknown", done: "Done", failed: "Failed", cancelled: "Cancelled" };
const WHAT: Record<Post["post"], string> = { handoff_request: "Handoff request", handoff: "Handoff result", task_result: "Task result" };
export function postChipText(entry: Post): string {
  const what = WHAT[entry.post];
  return [what, entry.title, entry.status ? STATUS[entry.status] ?? entry.status : ""].filter(Boolean).join(" · ");
}

/** A message another agent posted into this chat: avatar + name, its text, the handoff/task line, links. */
export function PostMessage({ entry, links, onOpenHandoff, onOpenChat, onReply, onOpenTaskArtifacts }: { entry: Post; links: Open; onOpenTaskArtifacts?:(taskId:string)=>void; onReply?: (handoffId: string) => void; onOpenHandoff?: (handoffId: string) => void; onOpenChat?: (sessionId: string) => void }) {
  const chip = postChipText(entry);
  const canOpen = entry.post !== "task_result" && entry.handoffId && onOpenHandoff;
  return (
    <article className={`jg-post jg-post--${entry.post}${entry.status ? ` is-${entry.status}` : ""}`} data-sender="post" aria-label={`${entry.sender.name}: ${chip}`}>
      <header className="jg-post__who">
        <AgentAvatar id={entry.sender.id} name={entry.sender.name} size={20} />
        <span className="jg-post__name">{entry.sender.name}</span>
      </header>
      <div className="jg-bubble jg-bubble--assistant jg-post__body">
        <Markdown text={entry.text} onOpen={links.onOpen} onCopy={links.onCopy} />
        <div className="jg-post__meta" data-thread-id={entry.threadId} data-reply-to={entry.replyTo}>
          {onReply && entry.handoffId && entry.post === "handoff" && ["completed", "failed", "cancelled", "rejected"].includes(entry.status ?? "") && <button type="button" onClick={() => onReply(entry.handoffId!)}>Follow up</button>}
          {canOpen
            ? <button type="button" className="jg-post__chip" onClick={() => onOpenHandoff!(entry.handoffId!)}>{chip}</button>
            : <span className="jg-post__chip">{chip}</span>}
          {entry.taskId&&onOpenTaskArtifacts&&<button type="button" onClick={()=>onOpenTaskArtifacts(entry.taskId!)}>Open task artifacts</button>}
          {entry.childSessionId && onOpenChat && (
            <button type="button" className="jg-post__link" onClick={() => onOpenChat(entry.childSessionId!)}>Open chat</button>
          )}
        </div>
      </div>
    </article>
  );
}
