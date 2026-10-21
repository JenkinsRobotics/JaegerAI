// One popup at a time, closed by Escape or any press outside it. Aether's Menu dismisses on `pointerdown`
// only; in WKWebView (native shell) a right-click leaves the secondary button "down" in WebKit's pointer
// state (no pointerup), so later left presses are chorded and fire mousedown/click but no pointerdown. Menus
// then ignored outside clicks and piled up. We listen to both and close every other popup when one opens.
import { useEffect, useRef } from "react";

export const POPUP_OPEN_EVENT = "jg:popup-open";
let seq = 0;
let openCount = 0;
let queued: (() => void) | null = null;

/** True while any coordinated popup is open. */
export function anyPopupOpen(): boolean { return openCount > 0; }
/** Run `fn` now, or (latest call wins) once the last open popup closes: the chat's auto-follow pauses
 * while a menu is open so the transcript doesn't scroll out from under it. */
export function whenNoPopup(fn: () => void): void {
  if (openCount === 0) fn(); else queued = fn;
}
function popupClosed(): void {
  openCount = Math.max(0, openCount - 1);
  if (openCount === 0 && queued) { const fn = queued; queued = null; fn(); }
}

type AnchorLike = Element | { x: number; y: number } | null | undefined;

export function useExclusivePopup(open: boolean, close: () => void, anchor?: AnchorLike): void {
  const id = useRef(`p${++seq}`);
  const closeRef = useRef(close);
  closeRef.current = close;
  const anchorRef = useRef(anchor);
  anchorRef.current = anchor;
  useEffect(() => {
    if (!open || typeof window === "undefined") return;
    const me = id.current;
    // Focus returns to the invoking control on close (GB-064), unless the user already moved it elsewhere.
    const invoker = document.activeElement instanceof HTMLElement && document.activeElement !== document.body ? document.activeElement : null;
    openCount += 1;
    window.dispatchEvent(new CustomEvent(POPUP_OPEN_EVENT, { detail: me }));
    const onOther = (e: Event) => { if ((e as CustomEvent).detail !== me) closeRef.current(); };
    const onPress = (e: Event) => {
      const t = e.target;
      if (t instanceof Element && t.closest("[role=menu],[role=dialog],[role=alertdialog],[data-jg-popup]")) return;
      const a = anchorRef.current;
      if (a instanceof Element && t instanceof Node && a.contains(t)) return;
      closeRef.current();
    };
    // Escape that cancels an IME composition belongs to the input method, not the popup.
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !e.isComposing && e.keyCode !== 229) closeRef.current(); };
    window.addEventListener(POPUP_OPEN_EVENT, onOther);
    document.addEventListener("mousedown", onPress, true);
    document.addEventListener("pointerdown", onPress, true);
    document.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener(POPUP_OPEN_EVENT, onOther);
      document.removeEventListener("mousedown", onPress, true);
      document.removeEventListener("pointerdown", onPress, true);
      document.removeEventListener("keydown", onKey, true);
      popupClosed();
      if (invoker) queueMicrotask(() => {
        const now = document.activeElement;
        const lost = !now || now === document.body || !now.isConnected;
        if (lost && invoker.isConnected) invoker.focus({ preventScroll: true });
      });
    };
  }, [open]);
}

/** Announce a popup that has no hook of its own (e.g. the ⌘K palette) so open menus close. */
export function announcePopup(id = "external"): void {
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(POPUP_OPEN_EVENT, { detail: id }));
}
