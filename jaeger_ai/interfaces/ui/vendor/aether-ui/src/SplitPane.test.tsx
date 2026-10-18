import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { SplitPane } from "./SplitPane";

test("renders horizontal panes with an accessible separator", () => {
  render(<SplitPane primary="Tree" secondary="Viewport" defaultPrimarySize={240} />);
  const separator = screen.getByRole("separator");
  expect(separator.getAttribute("aria-orientation")).toBe("vertical");
  expect(separator.getAttribute("aria-valuenow")).toBe("240");
});

test("keyboard resizing clamps and emits persistent size", () => {
  const onResize = vi.fn();
  render(<SplitPane primary="A" secondary="B" primarySize={200} minPrimarySize={180} maxPrimarySize={230} onResize={onResize} />);
  const separator = screen.getByRole("separator");
  fireEvent.keyDown(separator, { key: "ArrowRight", shiftKey: true });
  expect(onResize).toHaveBeenCalledWith(230);
  fireEvent.keyDown(separator, { key: "ArrowLeft", shiftKey: true });
  expect(onResize).toHaveBeenLastCalledWith(180);
});

test("Enter collapses and restore button expands", () => {
  const onCollapsedChange = vi.fn();
  const { rerender } = render(<SplitPane primary="A" secondary="B" collapsed={false} onCollapsedChange={onCollapsedChange} />);
  fireEvent.keyDown(screen.getByRole("separator"), { key: "Enter" });
  expect(onCollapsedChange).toHaveBeenCalledWith(true);
  rerender(<SplitPane primary="A" secondary="B" collapsed onCollapsedChange={onCollapsedChange} />);
  fireEvent.click(screen.getByText("Restore panel"));
  expect(onCollapsedChange).toHaveBeenLastCalledWith(false);
});

test("vertical pointer resize reports the new size", () => {
  const onResize = vi.fn();
  render(<SplitPane primary="Top" secondary="Bottom" orientation="vertical" primarySize={200} onResize={onResize} />);
  const down = new Event("pointerdown", { bubbles: true });
  Object.defineProperty(down, "clientY", { value: 20 });
  fireEvent(screen.getByRole("separator"), down);
  const move = new Event("pointermove", { bubbles: true });
  Object.defineProperty(move, "clientY", { value: 55 });
  fireEvent(document, move);
  fireEvent.pointerUp(document);
  expect(onResize).toHaveBeenCalledWith(235);
});
