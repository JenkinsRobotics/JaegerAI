import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Slider } from "./Slider";

describe("Slider", () => {
  it("publishes numeric values with native range semantics and units", () => {
    const onChange = vi.fn();
    render(<Slider ariaLabel="Environment intensity" defaultValue={50} min={0} max={200} step={5} unit="%" onChange={onChange} />);
    const input = screen.getByRole("slider", { name: "Environment intensity" });
    fireEvent.change(input, { target: { value: "75" } });
    expect(onChange).toHaveBeenCalledWith(75);
    expect(input.getAttribute("aria-valuetext")).toBe("75%");
    expect(screen.getByText("75%")).not.toBeNull();
  });

  it("supports controlled, hidden-output, and disabled states", () => {
    const { rerender } = render(<Slider ariaLabel="Opacity" value={0.25} min={0} max={1} step={0.05} showValue={false} />);
    expect(screen.queryByRole("status")).toBeNull();
    rerender(<Slider ariaLabel="Opacity" value={0.5} min={0} max={1} disabled />);
    expect((screen.getByRole("slider", { name: "Opacity" }) as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText("0.5")).not.toBeNull();
  });
});
