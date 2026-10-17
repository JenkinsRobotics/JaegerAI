import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Breadcrumbs } from "./Breadcrumbs";

describe("Breadcrumbs", () => {
  it("names the path, marks the current page, and emits stable navigation IDs", () => {
    const onNavigate = vi.fn();
    render(<Breadcrumbs ariaLabel="Model path" items={[
      { id: "workspace", label: "Atlas" },
      { id: "assembly", label: "Head Assembly" },
      { id: "part", label: "Jaw Bracket" },
    ]} onNavigate={onNavigate} />);
    expect(screen.getByRole("navigation", { name: "Model path" })).not.toBeNull();
    expect(screen.getByText("Jaw Bracket").getAttribute("aria-current")).toBe("page");
    fireEvent.click(screen.getByRole("button", { name: "Head Assembly" }));
    expect(onNavigate).toHaveBeenCalledWith("assembly");
  });

  it("keeps disabled locations inert", () => {
    const onNavigate = vi.fn();
    render(<Breadcrumbs items={[
      { id: "workspace", label: "Atlas", disabled: true },
      { id: "part", label: "Bracket" },
    ]} onNavigate={onNavigate} />);
    const disabled = screen.getByRole("button", { name: "Atlas" }) as HTMLButtonElement;
    expect(disabled.disabled).toBe(true);
    fireEvent.click(disabled);
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("collapses intermediate locations into the shared menu", () => {
    const onNavigate = vi.fn();
    render(<Breadcrumbs maxVisible={3} items={[
      { id: "workspace", label: "Atlas" },
      { id: "sub-1", label: "Robot" },
      { id: "sub-2", label: "Head" },
      { id: "sub-3", label: "Jaw" },
      { id: "part", label: "Bracket" },
    ]} onNavigate={onNavigate} />);
    expect(screen.queryByRole("button", { name: "Robot" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "More locations" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Head" }));
    expect(onNavigate).toHaveBeenCalledWith("sub-2");
    expect(screen.getByText("Bracket").getAttribute("aria-current")).toBe("page");
  });
});
