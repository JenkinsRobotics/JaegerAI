import { cloneElement, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { ReactElement, ReactNode } from "react";
import { useOverlayPosition, type OverlayPlacement } from "./overlay-position";

export interface TooltipProps {
  children: ReactElement<{ "aria-describedby"?: string }>;
  content: ReactNode;
  shortcut?: ReactNode;
  disabledReason?: ReactNode;
  delayMilliseconds?: number;
  placement?: OverlayPlacement;
}

/** Accessible delayed pointer help. Keyboard focus reveals immediately and the
 * trigger receives aria-describedby while the tooltip is present. */
export function Tooltip({
  children,
  content,
  shortcut,
  disabledReason,
  delayMilliseconds = 500,
  placement = "top-start",
}: TooltipProps) {
  const id = useId();
  const anchorRef = useRef<HTMLSpanElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [open, setOpen] = useState(false);
  const position = useOverlayPosition({
    open,
    overlayRef: tooltipRef,
    anchor: anchorRef.current,
    placement,
    gap: 7,
  });

  const clearTimer = () => {
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    timerRef.current = null;
  };
  const hide = () => {
    clearTimer();
    setOpen(false);
  };
  const showAfterDelay = () => {
    clearTimer();
    timerRef.current = setTimeout(() => setOpen(true), delayMilliseconds);
  };

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") hide();
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  });
  useEffect(() => () => clearTimer(), []);

  const describedBy = [children.props["aria-describedby"], open ? id : null]
    .filter(Boolean)
    .join(" ") || undefined;

  return (
    <>
      <span
        ref={anchorRef}
        className="aui-tooltip-anchor"
        onPointerEnter={showAfterDelay}
        onPointerLeave={hide}
        onFocusCapture={() => {
          clearTimer();
          setOpen(true);
        }}
        onBlurCapture={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) hide();
        }}
      >
        {cloneElement(children, { "aria-describedby": describedBy })}
      </span>
      {open && anchorRef.current && typeof document !== "undefined"
        ? createPortal(
            <div
              ref={tooltipRef}
              id={id}
              className="aui-tooltip"
              role="tooltip"
              style={position}
            >
              <span>{content}</span>
              {shortcut ? <kbd>{shortcut}</kbd> : null}
              {disabledReason ? <small>{disabledReason}</small> : null}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
