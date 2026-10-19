/* ⌘K Search: Grok's command palette (sand.commandPalette, hotkey mod+k; captured as a centred "Search" panel over
 * a dimmed window, final-check/grok-cmdk.png): a search field, then one row per bot (avatar, name, a one-line
 * description, blue unread dot), then Jaeger's few actions. Type to filter, ↑/↓ to move, Enter to open, Esc or a
 * click outside to close. Empty: No matches for "<query>" (Grok's string). */
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useExclusivePopup } from "../popups/coordinator";
import type { Agent, AgentSummary } from "../api/types";
import { Icon } from "../icons/Icon";
import { isUnread } from "./unread";
import { AgentAvatar } from "./AgentAvatar";
import { label } from "./agentsLogic";

export interface JumpAction { id: string; label: string; shortcut?: string; run: () => void }
type Row = { kind: "agent"; id: string; label: string; agent: Agent } | { kind: "action"; id: string; label: string; action: JumpAction };

/** One line under the name: the agent's own description when it has one, else its latest activity, else its role. */
export function describe(agent: Agent, summary?: AgentSummary): string {
  const own = agent.metadata?.description;
  if (typeof own === "string" && own.trim()) return own.trim();
  return summary?.last_preview?.trim() || (agent.role ? `${agent.role[0].toUpperCase()}${agent.role.slice(1)}` : "");
}

export function JumpTo({ open, agents, actions, onAgent, onClose, summaries = [], seen = {}, currentAgentId }: {
  open: boolean; agents: Agent[]; actions: JumpAction[]; onAgent: (agentId: string) => void; onClose: () => void;
  summaries?: AgentSummary[]; seen?: Record<string, number>; currentAgentId?: string;
}) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useExclusivePopup(open, onClose);
  useEffect(() => { if (open) { setQuery(""); setIndex(0); requestAnimationFrame(() => input.current?.focus()); } }, [open]);
  const rows = useMemo<Row[]>(() => {
    const q = query.trim().toLowerCase();
    const hit = (s: string) => !q || s.toLowerCase().includes(q);
    const desc = (a: Agent) => describe(a, summaries.find((x) => x.id === a.id));
    return [
      ...agents.filter((a) => hit(label(a)) || hit(desc(a))).map((a) => ({ kind: "agent" as const, id: a.id, label: label(a), agent: a })),
      ...actions.filter((a) => hit(a.label)).map((a) => ({ kind: "action" as const, id: a.id, label: a.label, action: a })),
    ];
  }, [query, agents, actions, summaries]);
  if (!open) return null;
  const pick = (row: Row) => { onClose(); if (row.kind === "agent") onAgent(row.id); else row.action.run(); };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setIndex((i) => Math.min(rows.length - 1, i + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setIndex((i) => Math.max(0, i - 1)); }
    else if (e.key === "Enter" && rows[index]) { e.preventDefault(); pick(rows[index]); }
    else if (e.key === "Escape") { e.preventDefault(); onClose(); }
  };
  const firstAction = rows.findIndex((r) => r.kind === "action");
  return (
    <div className="jg-palette__scrim" onMouseDown={onClose}>
      <div className="jg-palette" role="dialog" aria-label="Search" onMouseDown={(e) => e.stopPropagation()}>
        <div className="jg-palette__search">
          <Icon name="search" size={15} className="jg-palette__search-icon" />
          <input ref={input} className="jg-palette__input" placeholder="Search" aria-label="Search" value={query}
            onChange={(e) => { setQuery(e.target.value); setIndex(0); }} onKeyDown={onKey}
            role="combobox" aria-expanded aria-controls="jg-palette-list" aria-activedescendant={rows[index] ? `jg-palette-${index}` : undefined} />
        </div>
        <div className="jg-palette__list" id="jg-palette-list" role="listbox" aria-label="Results">
          {rows.length === 0 && <p className="jg-palette__empty">No matches for "{query.trim()}"</p>}
          {rows.map((row, i) => {
            const summary = row.kind === "agent" ? summaries.find((x) => x.id === row.id) : undefined;
            const description = row.kind === "agent" ? describe(row.agent, summary) : "";
            const unread = row.kind === "agent" && row.id !== currentAgentId
              && isUnread(row.id, summary?.last_activity_at ?? 0, seen, summary?.unseen);
            return (
              <div key={`${row.kind}:${row.id}`}>
                {i === firstAction && i > 0 && <div className="jg-palette__sep" role="separator" />}
                <div id={`jg-palette-${i}`} role="option" aria-selected={i === index}
                  className={`jg-palette__row${i === index ? " is-active" : ""}${description ? " has-desc" : ""}`}
                  onMouseEnter={() => setIndex(i)} onClick={() => pick(row)}>
                  {row.kind === "agent" ? <AgentAvatar id={row.agent.id} name={row.label} size={24} /> : <Icon name="chevron-right" size={14} className="jg-palette__icon" />}
                  <span className="jg-palette__text">
                    <span className="jg-palette__label">{row.label}</span>
                    {description && <span className="jg-palette__desc">{description}</span>}
                  </span>
                  {row.kind === "action" && row.action.shortcut && <kbd className="jg-palette__kbd">{row.action.shortcut}</kbd>}
                  {unread && <span className="jg-palette__dot" aria-label="Unread" />}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
