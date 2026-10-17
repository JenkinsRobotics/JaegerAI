import { render, screen } from "@testing-library/react";
import { useRef } from "react";
import { expect, test } from "vitest";
import { useOverlayPosition } from "./overlay-position";

function domRect(left: number, top: number, width: number, height: number): DOMRect {
  return {
    x: left,
    y: top,
    left,
    top,
    right: left + width,
    bottom: top + height,
    width,
    height,
    toJSON: () => ({}),
  } as DOMRect;
}

function PositionProbe({ anchor }: { anchor: HTMLElement }) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const style = useOverlayPosition({
    open: true,
    overlayRef,
    anchor,
    placement: "bottom-start",
  });
  return (
    <div
      data-testid="overlay"
      ref={(element) => {
        overlayRef.current = element;
        if (!element) return;
        element.getBoundingClientRect = () => domRect(0, 0, 200, 100);
      }}
      style={style}
    />
  );
}

test("flips above an anchor and clamps to the viewport edge", () => {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1000 });
  Object.defineProperty(window, "innerHeight", { configurable: true, value: 800 });
  const anchor = document.createElement("button");
  anchor.getBoundingClientRect = () => domRect(900, 730, 50, 30);

  render(<PositionProbe anchor={anchor} />);

  const overlay = screen.getByTestId("overlay");
  expect(overlay.style.left).toBe("792px");
  expect(overlay.style.top).toBe("625px");
  expect(overlay.style.visibility).toBe("visible");
});
