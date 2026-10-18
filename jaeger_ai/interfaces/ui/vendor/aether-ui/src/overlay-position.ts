import { useLayoutEffect, useState } from "react";
import type { CSSProperties, RefObject } from "react";

export interface OverlayPoint {
  x: number;
  y: number;
}

export type OverlayAnchor = HTMLElement | OverlayPoint;
export type OverlayPlacement =
  | "bottom-start"
  | "bottom-end"
  | "top-start"
  | "top-end"
  | "right-start"
  | "left-start";

interface OverlayPositionOptions {
  open: boolean;
  overlayRef: RefObject<HTMLElement | null>;
  anchor: OverlayAnchor | null;
  placement?: OverlayPlacement;
  gap?: number;
  viewportPadding?: number;
}

function isPoint(anchor: OverlayAnchor): anchor is OverlayPoint {
  return "x" in anchor && "y" in anchor;
}

/** Positions a fixed overlay beside an element or pointer location and clamps
 * it inside the viewport. Bottom/top placements flip when the preferred side
 * has insufficient space. */
export function useOverlayPosition({
  open,
  overlayRef,
  anchor,
  placement = "bottom-start",
  gap = 5,
  viewportPadding = 8,
}: OverlayPositionOptions): CSSProperties {
  const [position, setPosition] = useState<{ left: number; top: number } | null>(
    null,
  );

  useLayoutEffect(() => {
    if (!open || !anchor || !overlayRef.current) {
      setPosition(null);
      return;
    }

    const update = () => {
      const overlay = overlayRef.current;
      if (!overlay) return;
      const overlayRect = overlay.getBoundingClientRect();
      const width = overlayRect.width || overlay.offsetWidth;
      const height = overlayRect.height || overlay.offsetHeight;
      const viewportWidth = window.innerWidth;
      const viewportHeight = window.innerHeight;

      let left: number;
      let top: number;
      if (isPoint(anchor)) {
        left = anchor.x;
        top = anchor.y;
      } else {
        const rect = anchor.getBoundingClientRect();
        switch (placement) {
          case "bottom-end":
            left = rect.right - width;
            top = rect.bottom + gap;
            break;
          case "top-start":
            left = rect.left;
            top = rect.top - height - gap;
            break;
          case "top-end":
            left = rect.right - width;
            top = rect.top - height - gap;
            break;
          case "right-start":
            left = rect.right + gap;
            top = rect.top;
            break;
          case "left-start":
            left = rect.left - width - gap;
            top = rect.top;
            break;
          case "bottom-start":
          default:
            left = rect.left;
            top = rect.bottom + gap;
            break;
        }

        const requestsBottom = placement.startsWith("bottom");
        const requestsTop = placement.startsWith("top");
        if (
          requestsBottom &&
          top + height > viewportHeight - viewportPadding &&
          rect.top - gap - height >= viewportPadding
        ) {
          top = rect.top - gap - height;
        } else if (
          requestsTop &&
          top < viewportPadding &&
          rect.bottom + gap + height <= viewportHeight - viewportPadding
        ) {
          top = rect.bottom + gap;
        }
      }

      left = Math.min(
        Math.max(viewportPadding, left),
        Math.max(viewportPadding, viewportWidth - width - viewportPadding),
      );
      top = Math.min(
        Math.max(viewportPadding, top),
        Math.max(viewportPadding, viewportHeight - height - viewportPadding),
      );
      setPosition({ left, top });
    };

    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [anchor, gap, open, overlayRef, placement, viewportPadding]);

  return {
    position: "fixed",
    left: position?.left ?? 0,
    top: position?.top ?? 0,
    visibility: position ? "visible" : "hidden",
  };
}
