/* The message context menu, laid out like Grok's (final-check/grok-message-menu.png): a row of quick reactions,
 * then Reply, Copy and Copy request ID with icons (Grok strings "Add reaction", "Reply", "Copy request ID").
 * Reactions and allowed emojis come from the Gateway. Copy request ID uses admission identity and is
 * hidden when that identity is unknown. Popup coordinator: Esc, a click outside, one menu at a time. */
import { useLayoutEffect, useRef, useState } from "react";
import { useExclusivePopup } from "../popups/coordinator";
import { Icon, type IconName } from "../icons/Icon";

export type MessageAction = "reply" | "copy" | "copy-id" | `react:${string}`;

export function MessageMenu({ at, requestId, reactionEmojis = [], onAction, onClose }: {
  at: { x: number; y: number } | null; requestId?: string; reactionEmojis?: readonly string[]; onAction: (a: MessageAction) => void; onClose: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  useExclusivePopup(Boolean(at), onClose, at);
  useLayoutEffect(() => {
    if (!at || !box.current) { setPos(null); return; }
    const r = box.current.getBoundingClientRect();
    setPos({ left: Math.max(8, Math.min(at.x, innerWidth - r.width - 8)), top: Math.max(8, Math.min(at.y, innerHeight - r.height - 8)) });
  }, [at]);
  if (!at) return null;
  const items: { id: MessageAction; label: string; icon: IconName }[] = [
    { id: "reply", label: "Reply", icon: "reply" },
    { id: "copy", label: "Copy", icon: "copy" },
    ...(requestId ? [{ id: "copy-id" as const, label: "Copy request ID", icon: "link" as IconName }] : []),
  ];
  const pick = (a: MessageAction) => { onClose(); onAction(a); };
  return (
    <div ref={box} className="jg-msgmenu" role="menu" aria-label="Message actions" style={{ left: pos?.left ?? at.x, top: pos?.top ?? at.y, visibility: pos ? undefined : "hidden" }}
      onMouseDown={(e) => e.stopPropagation()} onKeyDown={(e) => { if (e.key === "Escape") { e.preventDefault(); onClose(); } }}>
      {reactionEmojis.length > 0 && <><div className="jg-msgmenu__reactions" role="group" aria-label="Add reaction">
        {reactionEmojis.map((r) => <button key={r} type="button" role="menuitem" className="jg-msgmenu__emoji" aria-label={`React ${r}`} onClick={() => pick(`react:${r}`)}>{r}</button>)}
      </div>
      <div className="jg-msgmenu__sep" role="separator" /></>}
      {items.map((it) => (
        <button key={it.id} type="button" role="menuitem" className="jg-msgmenu__item" onClick={() => pick(it.id)}>
          <Icon name={it.icon} size={14} />{it.label}
        </button>
      ))}
    </div>
  );
}

/** Confirmed reactions under a message; removal waits for the Gateway receipt. */
export function Reactions({ emojis, onRemove }: { emojis: string[]; onRemove: (e: string) => void }) {
  if (!emojis.length) return null;
  return (
    <div className="jg-reactions" aria-label="Reactions">
      {emojis.map((e) => <button key={e} type="button" className="jg-reaction" aria-label={`Remove reaction ${e}`} onClick={() => onRemove(e)}>{e}</button>)}
    </div>
  );
}
