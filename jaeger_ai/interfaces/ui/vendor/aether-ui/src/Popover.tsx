import { createPortal } from "react-dom";
import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import {
  useOverlayPosition,
  type OverlayAnchor,
  type OverlayPlacement,
} from "./overlay-position";

const FOCUSABLE =
  'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';

export interface PopoverProps {
  open: boolean;
  anchor: OverlayAnchor | null;
  onClose: () => void;
  children: ReactNode;
  ariaLabel: string;
  placement?: OverlayPlacement;
  /** `first` is useful for small editors; `none` preserves viewport focus. */
  focus?: "none" | "first";
  closeOnOutsidePress?: boolean;
  returnFocus?: boolean;
  className?: string;
}

/** Anchored nonmodal surface shared by compact editors and explanatory cards. */
export function Popover({
  open,
  anchor,
  onClose,
  children,
  ariaLabel,
  placement = "bottom-start",
  focus = "none",
  closeOnOutsidePress = true,
  returnFocus = true,
  className,
}: PopoverProps) {
  const popoverRef = useRef<HTMLDivElement>(null);
  const position = useOverlayPosition({
    open,
    overlayRef: popoverRef,
    anchor,
    placement,
  });

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    if (focus === "first") {
      popoverRef.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      onClose();
    };
    const onPointerDown = (event: PointerEvent) => {
      if (!closeOnOutsidePress) return;
      const target = event.target as Node;
      if (popoverRef.current?.contains(target)) return;
      if (anchor instanceof HTMLElement && anchor.contains(target)) return;
      onClose();
    };
    document.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("pointerdown", onPointerDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.removeEventListener("pointerdown", onPointerDown, true);
      if (returnFocus) opener?.focus?.();
    };
  }, [anchor, closeOnOutsidePress, focus, onClose, open, returnFocus]);

  if (!open || !anchor || typeof document === "undefined") return null;
  const classes = ["aui-popover"];
  if (className) classes.push(className);
  return createPortal(
    <div
      ref={popoverRef}
      className={classes.join(" ")}
      role="dialog"
      aria-modal="false"
      aria-label={ariaLabel}
      style={position}
    >
      {children}
    </div>,
    document.body,
  );
}
