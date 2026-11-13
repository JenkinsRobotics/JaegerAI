/* The selected agent's chats, under its row. Right-click: Rename chat / Archive chat.
 * Grouped by date like Codex / Cursor; filter box when the list is long. */
import { type MenuItem } from "@aether/ui";
import { AppMenu as Menu } from "../popups/AppMenu";
import { useMemo, useState, type KeyboardEvent } from "react";
import type { SessionRow } from "../api/types";
import { activityAt, chatTitle, groupChatsByDate, shortTime } from "./chats";

const MENU: MenuItem[] = [
  { id: "rename", label: "Rename chat" },
  { id: "archive", label: "Archive chat", danger: true, separatorBefore: true },
];

interface Props {
  rows: SessionRow[];
  openId?: string;
  onOpen: (sessionId: string) => void;
  onRename: (sessionId: string, title: string) => void;
  onArchive: (sessionId: string) => void;
}

export function ChatList({ rows, openId, onOpen, onRename, onArchive }: Props) {
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((row) => {
      const title = chatTitle(row).toLowerCase();
      const preview = (row.last_message_preview ?? "").toLowerCase();
      return title.includes(q) || preview.includes(q);
    });
  }, [rows, query]);
  const groups = useMemo(() => groupChatsByDate(filtered), [filtered]);
  if (!rows.length) return null;

  const commit = (id: string, value: string) => {
    setEditing(null);
    if (value.trim()) onRename(id, value.trim());
  };
  const onEditKey = (id: string) => (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") commit(id, event.currentTarget.value);
    if (event.key === "Escape") setEditing(null);
  };
  const rowEl = (row: SessionRow) => (
    <li key={row.session_id}>
      {editing === row.session_id ? (
        <input className="jg-chat-row__edit" autoFocus defaultValue={chatTitle(row)} aria-label="Chat name"
          onKeyDown={onEditKey(row.session_id)} onBlur={(e) => commit(row.session_id, e.currentTarget.value)} />
      ) : (
        <button type="button" className={`jg-chat-row${row.session_id === openId ? " is-open" : ""}`}
          aria-current={row.session_id === openId ? "page" : undefined} title={chatTitle(row)}
          onClick={() => onOpen(row.session_id)}
          onContextMenu={(e) => { e.preventDefault(); setMenu({ id: row.session_id, x: e.clientX, y: e.clientY }); }}>
          <span className="jg-chat-row__title">{chatTitle(row)}</span>
          <span className="jg-chat-row__time">{shortTime(activityAt(row))}</span>
        </button>
      )}
    </li>
  );

  return (
    <>
      {rows.length > 6 && (
        <label className="jg-chat-search">
          <span className="jg-sr-only">Search chats</span>
          <input type="search" value={query} placeholder="Search chats" aria-label="Search chats"
            onChange={(e) => setQuery(e.target.value)} />
        </label>
      )}
      {query.trim() && !filtered.length ? <p className="jg-chat-search__empty">No chats match “{query.trim()}”</p> : (
        groups.map((group) => (
          <div key={group.label} className="jg-chat-group">
            <div className="jg-chat-group__label" role="heading" aria-level={4}>{group.label}</div>
            <ul className="jg-chat-list" aria-label={group.label}>{group.rows.map(rowEl)}</ul>
          </div>
        ))
      )}
      <Menu open={Boolean(menu)} anchor={menu ? { x: menu.x, y: menu.y } : null} items={MENU} ariaLabel="Chat actions"
        onClose={() => setMenu(null)}
        onSelect={(id) => {
          const target = menu?.id;
          setMenu(null);
          if (!target) return;
          if (id === "rename") setEditing(target);
          if (id === "archive") onArchive(target);
        }} />
    </>
  );
}
