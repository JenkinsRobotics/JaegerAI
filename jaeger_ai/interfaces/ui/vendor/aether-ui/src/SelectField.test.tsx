import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { SelectField } from "./SelectField";

test("renders native options and reports selection changes", () => {
  const onChange = vi.fn();
  render(
    <SelectField
      aria-label="Units"
      defaultValue="mm"
      options={[
        { value: "mm", label: "Millimeters" },
        { value: "in", label: "Inches" },
      ]}
      onChange={onChange}
    />,
  );
  const select = screen.getByRole("combobox", { name: "Units" }) as HTMLSelectElement;
  fireEvent.change(select, { target: { value: "in" } });
  expect(select.value).toBe("in");
  expect(onChange).toHaveBeenCalledTimes(1);
});

test("exposes placeholder, disabled options, and invalid state", () => {
  render(
    <SelectField
      aria-label="Format"
      placeholder="Choose format"
      invalid
      options={[{ value: "legacy", label: "Legacy", disabled: true }]}
    />,
  );
  const select = screen.getByRole("combobox", { name: "Format" });
  expect(select.getAttribute("aria-invalid")).toBe("true");
  expect(screen.getByRole("option", { name: "Legacy" })).toHaveProperty("disabled", true);
});
