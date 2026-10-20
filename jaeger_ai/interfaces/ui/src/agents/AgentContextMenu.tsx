/* Agent popup follows the observed Mac reference. Presentation actions never
 * change execution roles, identity or conversation ownership. */
import { useLayoutEffect, useRef, useState } from "react";
import type { Agent } from "../api/types";
import { type AgentCaps } from "../api/agentActions";
import { useExclusivePopup } from "../popups/coordinator";
import { Icon, type IconName } from "../icons/Icon";
import { AgentAvatar } from "./AgentAvatar";
import { label } from "./agentsLogic";

export type AgentMenuAction = "rename" | "open" | "profile" | "history" | "read" | "unread" | "pin" | "unpin" | "section" | "template" | "hide" | "copy-id" | "duplicate" | "delete" | "replace-primary" | "make-primary";
type Item = { id: AgentMenuAction; label: string; icon: IconName; separator?: boolean };

export function agentMenuItems(agent: Agent, caps: AgentCaps, pinned: boolean, alternative = false): { main: Item[]; more: Item[] } {
  return { main: [
    ...(caps.pin ? [{ id: pinned ? "unpin" as const : "pin" as const, label: pinned ? "Unpin" : "Pin", icon: "pin" as IconName }] : []),
    ...(caps.unread ? [{ id: "unread" as const, label: "Mark as Unread", icon: "mail-read" as IconName }] : []),
    ...(!agent.primary && caps.rename ? [{ id: "rename" as const, label: "Rename Bot", icon: "edit" as IconName }] : []),
    { id: "copy-id", label: "Copy conversation ID", icon: "copy", separator: true },
    ...(caps.hide ? [{ id: "hide" as const, label: "Hide from sidebar", icon: "eye-closed" as IconName, separator: true }] : []),
    ...(agent.primary && caps.primary && alternative ? [{ id: "replace-primary" as const, label: "Replace with different Bot", icon: "reply" as IconName }] : []),
    ...(!agent.primary && caps.primary ? [{ id: "make-primary" as const, label: "Make primary", icon: "star-full" as IconName }] : []),
  ], more: [] };
}

export function AgentContextMenu({ agent, preview, at, phone, caps, pinned, alternative = false, onAction, onClose }: {
  agent: Agent; preview: string; at: { x: number; y: number }; phone: boolean; caps: AgentCaps; pinned: boolean; alternative?: boolean;
  onAction: (a: AgentMenuAction, agent: Agent) => void; onClose: () => void;
}) {
  const col = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  useExclusivePopup(true, onClose, at);
  useLayoutEffect(() => {
    const r = col.current?.getBoundingClientRect();
    if (!r) return;
    if (phone) { setPos({ left: Math.max(12, (innerWidth - r.width) / 2), top: Math.max(12, Math.min(96, innerHeight - r.height - 12)) }); return; }
    setPos({ left: Math.max(8, Math.min(at.x, innerWidth - r.width - 8)), top: Math.max(8, Math.min(at.y - 40, innerHeight - r.height - 8)) });
  }, [at, phone]);
  const { main } = agentMenuItems(agent, caps, pinned, alternative);
  const name = label(agent);
  const pick = (id: AgentMenuAction) => { onClose(); onAction(id, agent); };
  const row = (it: Item) => <div key={it.id}>
    {it.separator && <div className="jg-amenu__sep" role="separator" />}
    <button type="button" role="menuitem" className="jg-amenu__item" onClick={() => pick(it.id)}>
      {it.id === "replace-primary" ? <svg className="jg-amenu__swap" width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M3 5h12m-3-3 3 3-3 3M15 13H3m3-3-3 3 3 3" /></svg> : <Icon name={it.icon} size={18} />}<span>{it.label}</span>
    </button>
  </div>;
  return (
    <div className={`jg-amenu__scrim${phone ? " is-phone" : ""}`} onMouseDown={onClose} onTouchStart={(e) => { if (e.target === e.currentTarget) onClose(); }}
      onKeyDown={(e) => { if (e.key === "Escape") { e.preventDefault(); onClose(); } }}>
      <div ref={col} className="jg-amenu" style={pos ?? { visibility: "hidden" }} onMouseDown={(e) => e.stopPropagation()}>
        {phone && <section className="jg-amenu__preview" aria-label={`${name} preview`}>
          <header className="jg-amenu__head"><AgentAvatar id={agent.id} name={name} src={agent.avatar_url} size={30} /><b>{name}</b></header>
          <div className="jg-amenu__bubble">{preview || "No messages yet"}</div>
        </section>}
        <div className="jg-amenu__stack">
          <div className="jg-amenu__card" role="menu" aria-label={`${name} actions`}>
            {main.map(row)}
          </div>

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
