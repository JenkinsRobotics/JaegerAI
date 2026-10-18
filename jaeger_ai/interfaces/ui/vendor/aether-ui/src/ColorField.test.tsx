import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ColorField } from "./ColorField";

describe("ColorField", () => {
  it("synchronizes the native picker and normalized hex text", () => {
    const onChange = vi.fn();
    render(<ColorField ariaLabel="Body color" defaultValue="#AABBCC" onChange={onChange} />);
    const text = screen.getByLabelText("Body color") as HTMLInputElement;
    expect(text.value).toBe("#aabbcc");
    fireEvent.change(screen.getByLabelText("Body color picker"), { target: { value: "#112233" } });
    expect(text.value).toBe("#112233");
    expect(onChange).toHaveBeenCalledWith("#112233");
  });

  it("commits valid text, reports invalid text, and cancels with Escape", () => {
    const onChange = vi.fn();
    render(<ColorField ariaLabel="Edge color" defaultValue="#000000" onChange={onChange} />);
    const input = screen.getByLabelText("Edge color") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "#ABCDEF" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("#abcdef");
    fireEvent.change(input, { target: { value: "blue" } });
    fireEvent.blur(input);
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByRole("alert").textContent).toContain("six-digit hex");
    fireEvent.keyDown(input, { key: "Escape" });
    expect(input.value).toBe("#abcdef");
  });
});
