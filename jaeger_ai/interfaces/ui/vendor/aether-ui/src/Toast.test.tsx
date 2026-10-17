import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ToastStack } from "./Toast";

const items = [
  { id: "saved", kind: "success" as const, title: "Saved", message: "Document is current.", actionLabel: "Show" },
  { id: "failed", kind: "error" as const, title: "Export failed", message: "Source is unavailable." },
  { id: "running", kind: "progress" as const, title: "Importing", progress: 42, persistent: true },
];

describe("ToastStack", () => {
  it("announces status and errors with progress semantics", () => {
    render(<ToastStack items={items} />);
    expect(screen.getByRole("status", { name: /Saved/ })).not.toBeNull();
    expect(screen.getByRole("alert").textContent).toContain("Export failed");
    expect((screen.getByRole("progressbar", { name: "Importing progress" }) as HTMLProgressElement).value).toBe(42);
  });

  it("emits stable action and dismiss IDs while respecting persistence", () => {
    const onAction = vi.fn(); const onDismiss = vi.fn();
    render(<ToastStack items={items} onAction={onAction} onDismiss={onDismiss} />);
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    fireEvent.click(screen.getByRole("button", { name: "Dismiss Saved" }));
    expect(onAction).toHaveBeenCalledWith("saved");
    expect(onDismiss).toHaveBeenCalledWith("saved");
    expect(screen.queryByRole("button", { name: "Dismiss Importing" })).toBeNull();
  });
});
