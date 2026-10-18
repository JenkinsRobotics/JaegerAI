import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SegmentedControl } from "./SegmentedControl";

const options = [{ id: "shaded", label: "Shaded" }, { id: "blocked", label: "Blocked", disabled: true }, { id: "edges", label: "Edges" }];

describe("SegmentedControl", () => {
  it("supports uncontrolled selection and radio semantics", () => {
    const onChange = vi.fn();
    render(<SegmentedControl ariaLabel="Display style" options={options} defaultValue="shaded" onChange={onChange} />);
    fireEvent.click(screen.getByRole("radio", { name: "Edges" }));
    expect(screen.getByRole("radio", { name: "Edges" }).getAttribute("aria-checked")).toBe("true");
    expect(onChange).toHaveBeenCalledWith("edges");
  });

  it("wraps arrows and supports Home/End while skipping disabled segments", () => {
    const onChange = vi.fn();
    render(<SegmentedControl ariaLabel="Display style" options={options} value="shaded" onChange={onChange} />);
    fireEvent.keyDown(screen.getByRole("radio", { name: "Shaded" }), { key: "ArrowLeft" });
    expect(onChange).toHaveBeenLastCalledWith("edges");
    fireEvent.keyDown(screen.getByRole("radio", { name: "Shaded" }), { key: "Home" });
    expect(onChange).toHaveBeenLastCalledWith("shaded");
  });

  it("disables every segment at the group boundary", () => {
    render(<SegmentedControl ariaLabel="Mode" options={options} disabled />);
    expect(screen.getByRole("radiogroup", { name: "Mode" }).getAttribute("aria-disabled")).toBe("true");
    expect((screen.getByRole("radio", { name: "Shaded" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
