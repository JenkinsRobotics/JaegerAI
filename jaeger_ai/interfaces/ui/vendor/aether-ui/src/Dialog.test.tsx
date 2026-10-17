import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { Dialog } from "./Dialog";

test("renders nothing when closed and content when open", () => {
  const { rerender } = render(
    <Dialog open={false} title="T" onClose={() => {}}>
      body
    </Dialog>
  );
  expect(screen.queryByRole("dialog")).toBeNull();
  rerender(
    <Dialog open title="T" onClose={() => {}}>
      body
    </Dialog>
  );
  expect(screen.getByRole("dialog")).not.toBeNull();
});

test("scrim click and close button both close; body click does not", () => {
  const onClose = vi.fn();
  render(
    <Dialog open title="T" onClose={onClose}>
      body
    </Dialog>
  );
  fireEvent.click(screen.getByText("body"));
  expect(onClose).not.toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText("Close"));
  expect(onClose).toHaveBeenCalledTimes(1);
});

test("Escape closes regardless of where focus is", () => {
  const onClose = vi.fn();
  render(
    <Dialog open title="T" onClose={onClose}>
      body
    </Dialog>
  );
  fireEvent.keyDown(document.body, { key: "Escape" });
  expect(onClose).toHaveBeenCalledTimes(1);
});

test("focus moves into the dialog on open and Tab cycles within it", () => {
  render(
    <Dialog
      open
      title="T"
      onClose={() => {}}
      actions={<button type="button">OK</button>}
    >
      body
    </Dialog>
  );
  // First focusable (the Close button) receives focus on open.
  expect(document.activeElement).toBe(screen.getByLabelText("Close"));
  // Tab from the last focusable wraps to the first.
  screen.getByText("OK").focus();
  fireEvent.keyDown(document, { key: "Tab" });
  expect(document.activeElement).toBe(screen.getByLabelText("Close"));
  // Shift+Tab from the first wraps to the last.
  fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
  expect(document.activeElement).toBe(screen.getByText("OK"));
});
