import { fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { expect, test, vi } from "vitest";
import { Popover } from "./Popover";

function PopoverHarness({ onClose = () => {} }: { onClose?: () => void }) {
  const anchorRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  return (
    <>
      <button ref={anchorRef} onClick={() => setOpen(true)}>Open</button>
      <Popover
        open={open}
        anchor={anchorRef.current}
        ariaLabel="Properties"
        focus="first"
        onClose={() => {
          onClose();
          setOpen(false);
        }}
      >
        <button>Apply</button>
      </Popover>
    </>
  );
}

test("renders only while open and focuses the first control", () => {
  render(<PopoverHarness />);
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByText("Open"));
  expect(screen.getByRole("dialog", { name: "Properties" })).not.toBeNull();
  expect(document.activeElement).toBe(screen.getByText("Apply"));
});

test("inside presses stay open; outside press and Escape close", () => {
  const onClose = vi.fn();
  render(<PopoverHarness onClose={onClose} />);
  fireEvent.click(screen.getByText("Open"));
  fireEvent.pointerDown(screen.getByText("Apply"));
  expect(onClose).not.toHaveBeenCalled();
  fireEvent.pointerDown(document.body);
  expect(onClose).toHaveBeenCalledTimes(1);

  fireEvent.click(screen.getByText("Open"));
  fireEvent.keyDown(document, { key: "Escape" });
  expect(onClose).toHaveBeenCalledTimes(2);
});

test("returns focus to the opener on close", () => {
  render(<PopoverHarness />);
  const opener = screen.getByText("Open");
  opener.focus();
  fireEvent.click(opener);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(document.activeElement).toBe(opener);
});
