/* ⌘K "Jump to": Grok's command palette (sand.commandPalette, hotkey mod+k, label "Jump to"; its search
 * button is "Search Bots"), scoped to what Jaeger has: Bots and a few actions. Type to filter, ↑/↓ to move,
 * Enter to open, Esc or a click outside to close. Empty: No matches for "<query>" (Grok's string). */
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useExclusivePopup } from "../popups/coordinator";
import type { Agent } from "../api/types";
import { AgentAvatar } from "./AgentAvatar";
import { label } from "./agentsLogic";

export interface JumpAction { id: string; label: string; shortcut?: string; run: () => void }
type Row = { kind: "agent"; id: string; label: string; agent: Agent } | { kind: "action"; id: string; label: string; action: JumpAction };

export function JumpTo({ open, agents, actions, onAgent, onClose }: {
  open: boolean; agents: Agent[]; actions: JumpAction[]; onAgent: (agentId: string) => void; onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useExclusivePopup(open, onClose);
  useEffect(() => { if (open) { setQuery(""); setIndex(0); requestAnimationFrame(() => input.current?.focus()); } }, [open]);
  const rows = useMemo<Row[]>(() => {
    const q = query.trim().toLowerCase();
    const hit = (s: string) => !q || s.toLowerCase().includes(q);
    return [
      ...agents.filter((a) => hit(label(a))).map((a) => ({ kind: "agent" as const, id: a.id, label: label(a), agent: a })),
      ...actions.filter((a) => hit(a.label)).map((a) => ({ kind: "action" as const, id: a.id, label: a.label, action: a })),
    ];
  }, [query, agents, actions]);
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
      <div className="jg-palette" role="dialog" aria-label="Jump to" onMouseDown={(e) => e.stopPropagation()}>
        <input ref={input} className="jg-palette__input" placeholder="Jump to" aria-label="Jump to" value={query}
          onChange={(e) => { setQuery(e.target.value); setIndex(0); }} onKeyDown={onKey}
          role="combobox" aria-expanded aria-controls="jg-palette-list" aria-activedescendant={rows[index] ? `jg-palette-${index}` : undefined} />
        <div className="jg-palette__list" id="jg-palette-list" role="listbox" aria-label="Results">
          {rows.length === 0 && <p className="jg-palette__empty">No matches for "{query.trim()}"</p>}
          {rows.map((row, i) => (
            <div key={`${row.kind}:${row.id}`}>
              {i === 0 && row.kind === "agent" && <div className="jg-palette__group">Bots</div>}
              {i === firstAction && <div className="jg-palette__group">Actions</div>}
              <div id={`jg-palette-${i}`} role="option" aria-selected={i === index} className={`jg-palette__row${i === index ? " is-active" : ""}`}
                onMouseEnter={() => setIndex(i)} onClick={() => pick(row)}>
                {row.kind === "agent" ? <AgentAvatar id={row.agent.id} name={row.label} size={22} /> : <span className="jg-palette__icon" aria-hidden>›</span>}
                <span className="jg-palette__label">{row.label}</span>
                {row.kind === "action" && row.action.shortcut && <kbd className="jg-palette__kbd">{row.action.shortcut}</kbd>}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
