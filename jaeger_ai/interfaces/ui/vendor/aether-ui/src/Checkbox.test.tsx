import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { Checkbox } from "./Checkbox";

test("uses native checkbox interaction with shared label and description", () => {
  const onChange = vi.fn();
  render(<Checkbox label="Construction" description="Reference geometry" onChange={onChange} />);
  const checkbox = screen.getByRole("checkbox", { name: "Construction Reference geometry" });
  fireEvent.click(checkbox);
  expect(onChange).toHaveBeenCalledTimes(1);
  expect(screen.getByText("Reference geometry")).not.toBeNull();
});

test("pins the mixed multi-selection state", () => {
  render(<Checkbox label="Visible" indeterminate />);
  const checkbox = screen.getByRole("checkbox", { name: "Visible" }) as HTMLInputElement;
  expect(checkbox.indeterminate).toBe(true);
  expect(checkbox.getAttribute("aria-checked")).toBe("mixed");
});
