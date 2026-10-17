import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { NumberField } from "./NumberField";

test("commits arithmetic expressions and normalizes the display", () => {
  const onCommit = vi.fn();
  render(<NumberField aria-label="Width" defaultValue={10} unit="mm" onCommit={onCommit} />);
  const input = screen.getByRole("textbox", { name: "Width" }) as HTMLInputElement;
  fireEvent.input(input, { target: { value: "2 * (3 + 4)" } });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(onCommit).toHaveBeenCalledWith(14);
  expect(input.value).toBe("14");
  expect(screen.getByText("mm")).not.toBeNull();
});

test("rejects invalid or out-of-range drafts and Escape restores the commit", () => {
  render(<NumberField aria-label="Angle" defaultValue={30} min={0} max={90} />);
  const input = screen.getByRole("textbox", { name: "Angle" }) as HTMLInputElement;
  fireEvent.input(input, { target: { value: "120" } });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(input.getAttribute("aria-invalid")).toBe("true");
  fireEvent.keyDown(input, { key: "Escape" });
  expect(input.value).toBe("30");
  expect(input.getAttribute("aria-invalid")).toBeNull();
});

test("arrow keys step, with Shift for coarse and Alt for fine adjustment", () => {
  const onCommit = vi.fn();
  render(<NumberField aria-label="Offset" defaultValue={5} step={2} onCommit={onCommit} />);
  const input = screen.getByRole("textbox", { name: "Offset" }) as HTMLInputElement;
  fireEvent.keyDown(input, { key: "ArrowUp", shiftKey: true });
  expect(input.value).toBe("25");
  fireEvent.keyDown(input, { key: "ArrowDown", altKey: true });
  expect(input.value).toBe("24.8");
  expect(onCommit).toHaveBeenLastCalledWith(24.8);
});

test("the optional scrub handle changes and commits by pointer distance", () => {
  const onCommit = vi.fn();
  render(
    <NumberField
      aria-label="Depth"
      scrubLabel="Depth"
      defaultValue={10}
      step={0.5}
      onCommit={onCommit}
    />,
  );
  const pointerEvent = (type: string, clientX: number) => {
    const event = new Event(type, { bubbles: true });
    Object.defineProperty(event, "clientX", { value: clientX });
    return event;
  };
  fireEvent(
    screen.getByRole("button", { name: "Adjust Depth" }),
    pointerEvent("pointerdown", 10),
  );
  fireEvent(document, pointerEvent("pointermove", 20));
  fireEvent(document, pointerEvent("pointerup", 20));
  expect((screen.getByRole("textbox", { name: "Depth" }) as HTMLInputElement).value).toBe("15");
  expect(onCommit).toHaveBeenLastCalledWith(15);
});

test("mixed and externally controlled values update without losing field semantics", () => {
  const { rerender } = render(<NumberField aria-label="Scale" mixed />);
  const input = screen.getByRole("textbox", { name: "Scale" }) as HTMLInputElement;
  expect(input.placeholder).toBe("Mixed");
  rerender(<NumberField aria-label="Scale" value={2.5} precision={2} />);
  expect(input.value).toBe("2.50");
});
