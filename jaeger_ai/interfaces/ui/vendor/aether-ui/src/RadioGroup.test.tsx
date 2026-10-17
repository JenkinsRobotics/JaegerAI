import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RadioGroup } from "./RadioGroup";

const options = [{ id: "first", label: "First angle" }, { id: "blocked", label: "Blocked", disabled: true }, { id: "third", label: "Third angle", description: "ASME default" }];

describe("RadioGroup", () => {
  it("supports uncontrolled native selection and descriptions", () => {
    const onChange = vi.fn();
    render(<RadioGroup label="Projection standard" options={options} defaultValue="first" onChange={onChange} name="projection" />);
    const third = screen.getByRole("radio", { name: "Third angle ASME default" });
    fireEvent.click(third);
    expect((third as HTMLInputElement).checked).toBe(true);
    expect(onChange).toHaveBeenCalledWith("third");
  });

  it("uses arrows and Home/End while skipping disabled options", () => {
    const onChange = vi.fn();
    render(<RadioGroup label="Projection" options={options} value="first" onChange={onChange} />);
    fireEvent.keyDown(screen.getByLabelText("First angle"), { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith("third");
    fireEvent.keyDown(screen.getByLabelText("First angle"), { key: "End" });
    expect(onChange).toHaveBeenLastCalledWith("third");
  });

  it("exposes disabled and validation states", () => {
    render(<RadioGroup label="Source" options={options} disabled error="Choose a source." />);
    expect((screen.getByRole("group", { name: "Source" }) as HTMLFieldSetElement).disabled).toBe(true);
    expect(screen.getByRole("alert").textContent).toContain("Choose a source.");
  });
});
