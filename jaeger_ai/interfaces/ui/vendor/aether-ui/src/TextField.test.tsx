import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { TextField } from "./TextField";

test("invalid state sets aria-invalid and the error class", () => {
  render(<TextField invalid placeholder="angle" />);
  const input = screen.getByPlaceholderText("angle");
  expect(input.getAttribute("aria-invalid")).toBe("true");
  expect(input.className).toContain("aui-text-field--invalid");
});

test("unit suffix renders beside the input without entering its value", () => {
  render(<TextField unit="mm" defaultValue="12.5" placeholder="offset" />);
  expect(screen.getByText("mm")).not.toBeNull();
  const input = screen.getByPlaceholderText("offset") as HTMLInputElement;
  expect(input.value).toBe("12.5");
});
