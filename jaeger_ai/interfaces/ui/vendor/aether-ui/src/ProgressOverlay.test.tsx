import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ProgressOverlay } from "./ProgressOverlay";

test("renders determinate phase progress and actions", () => {
  const cancel = vi.fn();
  const background = vi.fn();
  render(
    <ProgressOverlay open label="Importing" phase="2 of 4" value={25} onCancel={cancel} onBackground={background} />,
  );
  const progress = screen.getByRole("progressbar", { name: "Importing" });
  expect(progress.getAttribute("aria-valuenow")).toBe("25");
  expect(screen.getByText("2 of 4")).not.toBeNull();
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Run in background" }));
  fireEvent.keyDown(document, { key: "Escape" });
  expect(cancel).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(screen.getByRole("button", { name: "Run in background" }));
  expect(cancel).toHaveBeenCalledTimes(2);
  expect(background).toHaveBeenCalledTimes(1);
});

test("pins hidden and indeterminate states", () => {
  const { rerender } = render(<ProgressOverlay open={false} label="Rebuilding" />);
  expect(screen.queryByRole("progressbar")).toBeNull();
  rerender(<ProgressOverlay open inline label="Rebuilding" />);
  expect(screen.getByRole("progressbar", { name: "Rebuilding" }).getAttribute("aria-valuenow")).toBeNull();
});
