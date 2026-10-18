/* The selected agent's chats, under its row (Grok Bot: every chat keeps a
 * place in the sidebar). Right-click: Rename chat / Archive chat. */
import { type MenuItem } from "@aether/ui";
import { AppMenu as Menu } from "../popups/AppMenu";
import { useState, type KeyboardEvent } from "react";
import type { SessionRow } from "../api/types";
import { activityAt, chatTitle, shortTime } from "./chats";

const COLLAPSED_COUNT = 5;
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
  const [expanded, setExpanded] = useState(false);
  if (!rows.length) return null;

  const openIndex = rows.findIndex((r) => r.session_id === openId);
  const limit = expanded ? rows.length : Math.max(COLLAPSED_COUNT, openIndex + 1);
  const shown = rows.slice(0, limit);
  const commit = (id: string, value: string) => {
    setEditing(null);
    if (value.trim()) onRename(id, value.trim());
  };
  const onEditKey = (id: string) => (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") commit(id, event.currentTarget.value);
    if (event.key === "Escape") setEditing(null);
  };

  return (
    <>
      <ul className="jg-chat-list" aria-label="Chats">
        {shown.map((row) => (
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
        ))}
        {rows.length > shown.length && (
          <li><button type="button" className="jg-chat-row jg-chat-row--more" onClick={() => setExpanded(true)}>Show {rows.length - shown.length} more</button></li>
        )}
      </ul>
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
