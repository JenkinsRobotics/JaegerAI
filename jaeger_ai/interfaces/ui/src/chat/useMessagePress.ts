import { useCallback, useEffect, useRef, type PointerEvent, type MouseEvent, type KeyboardEvent } from "react";

export type MessageAnchor = { x: number; y: number; touch: boolean };
const INTERACTIVE = "a,button,input,textarea,select,[contenteditable=true],summary,[data-native-selection]";
const HOLD_MS = 450;
const MOVE_PX = 10;

/** A touch hold must never capture a scroll, a link, a multi-touch gesture or a desktop selection. */
export function useMessagePress(open: (bubble: HTMLElement, at: MessageAnchor) => void) {
  const latest = useRef(open); latest.current = open;
  const pending = useRef<{ id: number; x: number; y: number; bubble: HTMLElement; timer: ReturnType<typeof setTimeout> } | undefined>(undefined);
  const ignoreClickUntil = useRef(0);
  const cancel = useCallback(() => {
    if (!pending.current) return;
    clearTimeout(pending.current.timer);
    pending.current.bubble.classList.remove("jg-bubble--holding");
    pending.current = undefined;
  }, []);
  useEffect(() => {
    window.addEventListener("blur", cancel);
    document.addEventListener("visibilitychange", cancel);
    return () => { cancel(); window.removeEventListener("blur", cancel); document.removeEventListener("visibilitychange", cancel); };
  }, [cancel]);
  const bubbleAt = (target: EventTarget | null) => target instanceof Element && !target.closest(INTERACTIVE) ? target.closest<HTMLElement>(".jg-bubble") : null;
  return {
    cancel,
    onPointerDown(event: PointerEvent<HTMLElement>) {
      cancel();
      if (!["touch", "pen"].includes(event.pointerType) || event.isPrimary === false || event.button !== 0) return;
      const bubble = bubbleAt(event.target);
      if (!bubble) return;
      const { pointerId: id, clientX: x, clientY: y } = event;
      bubble.classList.add("jg-bubble--holding");
      const timer = setTimeout(() => {
        cancel();
        ignoreClickUntil.current = Date.now() + 1200;
        window.getSelection()?.removeAllRanges();
        latest.current(bubble, { x, y, touch: true });
      }, HOLD_MS);
      pending.current = { id, x, y, bubble, timer };
    },
    onPointerMove(event: PointerEvent<HTMLElement>) {
      const hold = pending.current;
      if (hold && (event.pointerId !== hold.id || Math.hypot(event.clientX - hold.x, event.clientY - hold.y) > MOVE_PX)) cancel();
    },
    onPointerUp(event: PointerEvent<HTMLElement>) {
      cancel();
      if (Date.now() < ignoreClickUntil.current && event.pointerType !== "mouse") event.preventDefault();
    },
    onPointerCancel: cancel,
    onClickCapture(event: MouseEvent<HTMLElement>) {
      if (Date.now() < ignoreClickUntil.current) { event.preventDefault(); event.stopPropagation(); ignoreClickUntil.current = 0; }
    },
    onContextMenu(event: MouseEvent<HTMLElement>) {
      const bubble = bubbleAt(event.target);
      if (!bubble) return;
      event.preventDefault();
      const touch = Boolean(pending.current) || (event.nativeEvent as globalThis.PointerEvent).pointerType === "touch";
      cancel();
      if (Date.now() < ignoreClickUntil.current) return;
      latest.current(bubble, { x: event.clientX, y: event.clientY, touch });
    },
    onKeyDown(event: KeyboardEvent<HTMLElement>) {
      if (event.key !== "ContextMenu" && !(event.shiftKey && event.key === "F10")) return;
      const bubble = bubbleAt(event.target);
      if (!bubble) return;
      event.preventDefault();
      const rect = bubble.getBoundingClientRect();
      latest.current(bubble, { x: rect.left + Math.min(32, rect.width / 2), y: rect.top + Math.min(32, rect.height / 2), touch: false });
    },
  };
}
