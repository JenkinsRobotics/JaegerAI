/* One real command surface for touch hold, right click and the keyboard menu key.
 * Reactions and request identities are Gateway-owned; unsupported commands explain why. */
import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useExclusivePopup } from "../popups/coordinator";
import { Icon, type IconName } from "../icons/Icon";
import type { MessageAnchor } from "./useMessagePress";

export type MessageAction = "reply" | "mark-unread" | "copy" | "select-text" | "copy-id" | `react:${string}`;

export function MessageMenu({ at, requestId, reactionEmojis = [], activeReactions = [], unreadAvailable = false, replyAvailable = true, onAction, onClose }: {
  at: MessageAnchor | null; requestId?: string; reactionEmojis?: readonly string[]; activeReactions?: readonly string[];
  unreadAvailable?: boolean; replyAvailable?: boolean; onAction: (a: MessageAction) => void; onClose: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number; bottom: number; maxHeight: number } | null>(null);
  useExclusivePopup(Boolean(at), onClose, at);
  useLayoutEffect(() => {
    if (!at || !box.current) { setPos(null); return; }
    const invoker = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const place = () => {
      const r = box.current!.getBoundingClientRect();
      const viewport = window.visualViewport;
      const left = viewport?.offsetLeft ?? 0, top = viewport?.offsetTop ?? 0;
      const width = viewport?.width ?? innerWidth, height = viewport?.height ?? innerHeight;
      setPos({ left: Math.max(left + 8, Math.min(at.x, left + width - r.width - 8)), top: Math.max(top + 8, Math.min(at.y, top + height - r.height - 8)), bottom: Math.max(8, innerHeight - top - height + 8), maxHeight: height - 24 });
    };
    place();
    box.current.querySelector<HTMLElement>('button:not(:disabled)')?.focus({ preventScroll: true });
    window.addEventListener("resize", place);
    window.visualViewport?.addEventListener("resize", place);
    return () => {
      window.removeEventListener("resize", place); window.visualViewport?.removeEventListener("resize", place);
      queueMicrotask(() => { if (invoker?.isConnected && (!document.activeElement || document.activeElement === document.body)) invoker.focus({ preventScroll: true }); });
    };
  }, [at]);
  if (!at) return null;
  const items: { id: MessageAction; label: string; icon: IconName; disabled?: boolean; reason?: string }[] = [
    { id: "reply", label: "Reply", icon: "reply", disabled: !replyAvailable, reason: "Wait until your draft is ready" },
    { id: "mark-unread", label: "Mark as unread", icon: "mail-read", disabled: !unreadAvailable, reason: "Unread markers are unavailable for this message on this Gateway" },
    { id: "copy", label: "Copy", icon: "copy" },
    { id: "select-text", label: "Select Text", icon: "edit" },
    { id: "copy-id", label: "Copy Request ID", icon: "link", disabled: !requestId, reason: "No request ID was recorded for this message" },
  ];
  const pick = (action: MessageAction) => { onAction(action); onClose(); };
  return createPortal(<>
    {at.touch && <div className="jg-msgmenu__backdrop" aria-hidden="true" onClick={onClose} />}
    <div ref={box} className={`jg-msgmenu${at.touch ? " jg-msgmenu--touch" : ""}`} role="menu" aria-label="Message actions"
      style={at.touch ? { bottom: pos?.bottom, maxHeight: pos?.maxHeight } : { left: pos?.left ?? at.x, top: pos?.top ?? at.y, visibility: pos ? undefined : "hidden" }}
      onMouseDown={e => e.stopPropagation()} onKeyDown={e => {
        if (e.key === "Escape") { e.preventDefault(); onClose(); return; }
        const buttons = Array.from(box.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []);
        const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
        const direction = ["ArrowDown", "ArrowRight"].includes(e.key) ? 1 : ["ArrowUp", "ArrowLeft"].includes(e.key) ? -1 : 0;
        if (direction || e.key === "Home" || e.key === "End" || e.key === "Tab") {
          e.preventDefault();
          const next = e.key === "Home" ? 0 : e.key === "End" ? buttons.length - 1 : (current + (direction || (e.shiftKey ? -1 : 1)) + buttons.length) % buttons.length;
          buttons[next]?.focus();
        }
      }}>
      {at.touch && <span className="jg-msgmenu__handle" aria-hidden="true" />}
      {reactionEmojis.length > 0 && <><div className="jg-msgmenu__reactions" role="group" aria-label="Add reaction">
        {reactionEmojis.map(emoji => <button key={emoji} type="button" role="menuitemcheckbox" aria-checked={activeReactions.includes(emoji)} className="jg-msgmenu__emoji" aria-label={`React ${emoji}`} onClick={() => pick(`react:${emoji}`)}>{emoji}</button>)}
      </div><div className="jg-msgmenu__sep" role="separator" /></>}
      {items.map(item => <button key={item.id} type="button" role="menuitem" className="jg-msgmenu__item" disabled={item.disabled} title={item.disabled ? item.reason : undefined} onClick={() => pick(item.id)}>
        <Icon name={item.icon} size={18} />{item.label}
      </button>)}
      {!requestId ? <small className="jg-msgmenu__note">No request ID was recorded for this message.</small> : !unreadAvailable && <small className="jg-msgmenu__note">Unread markers are unavailable on this Gateway.</small>}
      {at.touch && <button type="button" role="menuitem" className="jg-msgmenu__dismiss" onClick={onClose}>Close</button>}
    </div>
  </>, document.body);
}

/** Selectable plain text keeps native touch handles available without opening the composer. */
export function MessageTextSelection({ text, returnFocus, onCopy, onClose }: { text: string; returnFocus?: HTMLElement | null; onCopy: (text: string) => void; onClose: () => void }) {
  const field = useRef<HTMLTextAreaElement>(null);
  useExclusivePopup(true, onClose);
  useLayoutEffect(() => {
    const invoker = returnFocus ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    field.current?.focus({ preventScroll: true }); field.current?.select();
    return () => { queueMicrotask(() => { if (invoker?.isConnected && (!document.activeElement || document.activeElement === document.body)) invoker.focus({ preventScroll: true }); }); };
  }, []);
  return createPortal(<div className="jg-text-select__backdrop" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="jg-text-select" role="dialog" aria-modal="true" aria-label="Select message text" onKeyDown={event => {
      if (event.key !== "Tab") return;
      const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("textarea,button"));
      const index = controls.indexOf(document.activeElement as HTMLElement);
      if (event.shiftKey && index === 0) { event.preventDefault(); controls.at(-1)?.focus(); }
      else if (!event.shiftKey && index === controls.length - 1) { event.preventDefault(); controls[0]?.focus(); }
    }}>
      <header><strong>Select Text</strong><button type="button" onClick={onClose} aria-label="Close text selection"><Icon name="close" /></button></header>
      <p>Select the part you want to copy, or select all.</p>
      <textarea ref={field} aria-label="Message text" readOnly value={text} data-native-selection />
      <footer><button type="button" onClick={() => { field.current?.focus(); field.current?.select(); }}>Select all</button><button type="button" onClick={() => {
        const element = field.current;
        if (element) onCopy(element.value.slice(element.selectionStart, element.selectionEnd));
      }}>Copy selection</button><button type="button" onClick={onClose}>Done</button></footer>
    </section>
  </div>, document.body);
}

/** Confirmed reactions under a message; removal waits for the Gateway receipt. */
export function Reactions({ emojis, onRemove }: { emojis: string[]; onRemove: (e: string) => void }) {
  if (!emojis.length) return null;
  return <div className="jg-reactions" aria-label="Reactions">
    {emojis.map(e => <button key={e} type="button" className="jg-reaction" aria-label={`Remove reaction ${e}`} onClick={() => onRemove(e)}>{e}</button>)}
  </div>;
}
