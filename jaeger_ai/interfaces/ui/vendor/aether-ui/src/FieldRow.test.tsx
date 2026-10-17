import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { FieldRow } from "./FieldRow";

test("labels its editor and shows help", () => {
  render(
    <FieldRow label="Name" htmlFor="name" help="Stable display name">
      <input id="name" />
    </FieldRow>,
  );
  expect(screen.getByRole("textbox", { name: "Name" })).not.toBeNull();
  expect(screen.getByText("Stable display name")).not.toBeNull();
});

test("shows modified/error state and executes reset", () => {
  const onReset = vi.fn();
  render(
    <FieldRow label="Width" htmlFor="width" modified error="Must be positive" onReset={onReset}>
      <input id="width" />
    </FieldRow>,
  );
  expect(screen.getByRole("alert").textContent).toBe("Must be positive");
  expect(document.querySelector(".aui-field-row--modified")).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Reset" }));
  expect(onReset).toHaveBeenCalledTimes(1);
});
