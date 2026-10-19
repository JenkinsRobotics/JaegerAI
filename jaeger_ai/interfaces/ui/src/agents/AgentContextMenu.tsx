/* The agent context menu (right-click on the Mac, long-press on the phone), from Grok Bot iOS refs
 * (parity2/agent-menu/ref): the page behind blurs and dims; a PREVIEW card (avatar + bold name, divider, the latest
 * message in a grey bubble clamped with …) sits above a translucent menu: Mark Read, Pin, New Section, Share as
 * Template, Hide (red), More ›. More expands in place: the first menu dims and a second card overlaps its lower
 * part with Copy ID, Duplicate, Delete (red). Grok's "Ask Siri" is iOS-only and is dropped.
 * Items without a backing API (agentCaps) are hidden; Mark Read and Pin then use the local seen mark and pins.
 * Delete always asks first (soft delete on the gateway) and is never offered for protected agents. */
import { useLayoutEffect, useRef, useState } from "react";
import type { Agent } from "../api/types";
import { isProtected, type AgentCaps } from "../api/agentActions";
import { useExclusivePopup } from "../popups/coordinator";
import { Icon, type IconName } from "../icons/Icon";
import { AgentAvatar } from "./AgentAvatar";
import { label } from "./agentsLogic";

export type AgentMenuAction = "read" | "pin" | "unpin" | "section" | "template" | "hide" | "copy-id" | "duplicate" | "delete";
type Item = { id: AgentMenuAction; label: string; icon: IconName; danger?: boolean };

export function agentMenuItems(agent: Agent, caps: AgentCaps, pinned: boolean): { main: Item[]; more: Item[] } {
  const main: Item[] = [
    { id: "read", label: "Mark Read", icon: "pass" },
    pinned ? { id: "unpin", label: "Unpin", icon: "pin" } : { id: "pin", label: "Pin", icon: "pin" },
    ...(caps.sections ? [{ id: "section" as const, label: "New Section", icon: "new-folder" as IconName }] : []),
    ...(caps.template ? [{ id: "template" as const, label: "Share as Template", icon: "share" as IconName }] : []),
    ...(caps.hide && !isProtected(agent) ? [{ id: "hide" as const, label: "Hide", icon: "eye-closed" as IconName, danger: true }] : []),
  ];
  const more: Item[] = [
    { id: "copy-id", label: "Copy ID", icon: "copy" },
    ...(caps.duplicate ? [{ id: "duplicate" as const, label: "Duplicate", icon: "diff-added" as IconName }] : []),
    ...(caps.remove && !isProtected(agent) ? [{ id: "delete" as const, label: "Delete", icon: "trash" as IconName, danger: true }] : []),
  ];
  return { main, more };
}

export function AgentContextMenu({ agent, preview, at, phone, caps, pinned, onAction, onClose }: {
  agent: Agent; preview: string; at: { x: number; y: number }; phone: boolean; caps: AgentCaps; pinned: boolean;
  onAction: (a: AgentMenuAction, agent: Agent) => void; onClose: () => void;
}) {
  const [more, setMore] = useState(false);
  const col = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  useExclusivePopup(true, onClose, at);
  useLayoutEffect(() => {
    const r = col.current?.getBoundingClientRect();
    if (!r) return;
    if (phone) { setPos({ left: Math.max(12, (innerWidth - r.width) / 2), top: Math.max(12, Math.min(96, innerHeight - r.height - 12)) }); return; }
    setPos({ left: Math.max(8, Math.min(at.x, innerWidth - r.width - 8)), top: Math.max(8, Math.min(at.y - 40, innerHeight - r.height - 8)) });
  }, [at, phone]);
  const { main, more: moreItems } = agentMenuItems(agent, caps, pinned);
  const name = label(agent);
  const pick = (id: AgentMenuAction) => { onClose(); onAction(id, agent); };
  const row = (it: Item) => (
    <button key={it.id} type="button" role="menuitem" className={`jg-amenu__item${it.danger ? " is-danger" : ""}`} onClick={() => pick(it.id)}>
      <Icon name={it.icon} size={18} /><span>{it.label}</span>
    </button>
  );
  return (
    <div className={`jg-amenu__scrim${phone ? " is-phone" : ""}`} onMouseDown={onClose} onTouchStart={(e) => { if (e.target === e.currentTarget) onClose(); }}
      onKeyDown={(e) => { if (e.key === "Escape") { e.preventDefault(); if (more) setMore(false); else onClose(); } }}>
      <div ref={col} className="jg-amenu" style={pos ?? { visibility: "hidden" }} onMouseDown={(e) => e.stopPropagation()}>
        <section className="jg-amenu__preview" aria-label={`${name} preview`}>
          <header className="jg-amenu__head"><AgentAvatar id={agent.id} name={name} src={agent.avatar_url} size={30} /><b>{name}</b></header>
          <div className="jg-amenu__bubble">{preview || "No messages yet"}</div>
        </section>
        <div className="jg-amenu__stack">
          <div className={`jg-amenu__card${more ? " is-dimmed" : ""}`} role="menu" aria-label={`${name} actions`} aria-hidden={more || undefined}>
            {main.map(row)}
            <button type="button" role="menuitem" className="jg-amenu__item" aria-expanded={more} onClick={() => setMore(true)}>
              <Icon name="ellipsis" size={18} /><span>More</span><Icon name="chevron-right" size={16} className="jg-amenu__chev" />
            </button>
          </div>
          {more && (
            <div className="jg-amenu__card jg-amenu__more" role="menu" aria-label="More">
              <button type="button" role="menuitem" className="jg-amenu__item is-title" aria-expanded onClick={() => setMore(false)}>
                <Icon name="ellipsis" size={18} /><span>More</span><Icon name="chevron-down" size={16} className="jg-amenu__chev" />
              </button>
              <div className="jg-amenu__sep" role="separator" />
              {moreItems.map(row)}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/** Confirm (Delete) or name (New Section, Duplicate) prompt in the same visual language. */
export function AgentPrompt({ title, message, confirm, danger, input, onDone }: {
  title: string; message?: string; confirm: string; danger?: boolean; input?: { placeholder: string; value?: string };
  onDone: (ok: boolean, value?: string) => void;
}) {
  const [value, setValue] = useState(input?.value ?? "");
  useExclusivePopup(true, () => onDone(false));
  const ok = !input || value.trim().length > 0;
  return (
    <div className="jg-amenu__scrim" onMouseDown={() => onDone(false)}>
      <form className="jg-aprompt" role="alertdialog" aria-label={title} onMouseDown={(e) => e.stopPropagation()}
        onSubmit={(e) => { e.preventDefault(); if (ok) onDone(true, value.trim()); }}>
        <h3>{title}</h3>
        {message && <p>{message}</p>}
        {input && <input autoFocus aria-label={input.placeholder} placeholder={input.placeholder} value={value} onChange={(e) => setValue(e.target.value)} />}
        <div className="jg-aprompt__actions">
          <button type="button" onClick={() => onDone(false)}>Cancel</button>
          <button type="submit" className={danger ? "is-danger" : "is-primary"} disabled={!ok}>{confirm}</button>
        </div>
      </form>
    </div>
  );
}
