/* History (Grok-style sessions): an agent's older chats, read-only. The home chat is where you talk;
 * this panel only lists and shows what came before. */
import { useEffect, useState } from "react";
import type { HistoryRow, HomePage, HomeSessions } from "../chat/homeSession";
import { Markdown } from "../chat/Markdown";
import type { ChatPart } from "../chat/host";
import { PostMessage, SummaryCard } from "../chat/HomeEntries";
import { avatarColor } from "./avatarColor";
import { shortTime } from "./chats";
import type { CSSProperties } from "react";

const text = (parts: ChatPart[]) => parts.filter((p) => p.kind === "markdownContent").map((p) => (p as { text: string }).text).join("\n\n");
const noop = () => {};

export function HistoryPanel({ agentName, agentId, home, onOpenLink = noop, onClose }: {
  agentName: string; agentId: string; home: HomeSessions; onOpenLink?: (url: string) => void; onClose: () => void;
}) {
  const [rows, setRows] = useState<HistoryRow[] | null>(null);
  const [error, setError] = useState<string>();
  const [open, setOpen] = useState<{ row: HistoryRow; page?: HomePage; error?: string } | null>(null);
  useEffect(() => {
    let live = true;
    setRows(null); setOpen(null); setError(undefined);
    home.history(agentId).then((r) => { if (live) setRows(r); }, (e: unknown) => { if (live) setError(String((e as Error)?.message ?? e)); });
    return () => { live = false; };
  }, [home, agentId]);
  const show = (row: HistoryRow) => {
    setOpen({ row });
    home.read(row.sessionId).then((page) => setOpen((o) => (o?.row === row ? { row, page } : o)),
      (e: unknown) => setOpen((o) => (o?.row === row ? { row, error: String((e as Error)?.message ?? e) } : o)));
  };
  const links = { onOpen: onOpenLink, onCopy: noop };
  return (
    <aside className="jg-details jg-history" aria-label={`${agentName} history`} style={{ "--jg-agent-color": avatarColor(agentId) } as CSSProperties}>
      <header className="jg-details__head">
        {open && <button type="button" className="jg-round-button" aria-label="Back to history" onClick={() => setOpen(null)}>‹</button>}
        <div className="jg-details__who">
          <strong>{open ? open.row.title : "History"}</strong>
          <span className="jg-muted">{open ? `Read-only · ${shortTime((open.row.updatedAt ?? 0) / 1000)}` : `Older chats with ${agentName}`}</span>
        </div>
        <button type="button" className="jg-round-button" aria-label="Close history" onClick={onClose}>×</button>
      </header>
      {!open && (
        error ? <p className="jg-muted" role="alert">Couldn't load history: {error}</p>
        : !rows ? <p className="jg-muted">Loading…</p>
        : !rows.length ? <p className="jg-muted">No older chats. Everything with {agentName} is in its chat.</p>
        : (
          <ul className="jg-history__list">
            {rows.map((row) => (
              <li key={row.sessionId}>
                <button type="button" className="jg-history__row" onClick={() => show(row)}>
                  <span className="jg-history__title">{row.title}</span>
                  <span className="jg-history__time">{row.updatedAt ? shortTime(row.updatedAt / 1000) : ""}</span>
                  {row.preview && <span className="jg-history__preview">{row.preview}</span>}
                </button>
              </li>
            ))}
          </ul>
        )
      )}
      {open && (
        <div className="jg-history__view" aria-label="Read-only transcript">
          {open.error ? <p className="jg-muted" role="alert">Couldn't open this chat: {open.error}</p>
          : !open.page ? <p className="jg-muted">Loading…</p>
          : open.page.turns.map((turn) => {
            const entry = open.page!.entries[turn.turnId];
            if (entry?.kind === "summary") return <SummaryCard key={turn.turnId} entry={entry} links={links} />;
            if (entry?.kind === "post") return <PostMessage key={turn.turnId} entry={entry} links={links} />;
            return (
              <div key={turn.turnId} className="jg-history__turn">
                {turn.message && <div className="jg-bubble jg-bubble--user">{turn.message}</div>}
                {text(turn.parts) && <div className="jg-bubble jg-bubble--assistant"><Markdown text={text(turn.parts)} onOpen={links.onOpen} onCopy={noop} /></div>}
              </div>
            );
          })}
        </div>
      )}
    </aside>
  );
}
