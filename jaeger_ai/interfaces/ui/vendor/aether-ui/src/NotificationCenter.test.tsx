import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NotificationCenter } from "./NotificationCenter";

const items = [
  { id: "warn", kind: "warning" as const, title: "Linked source changed", timestamp: "Now", actionLabel: "Review" },
  { id: "done", kind: "success" as const, title: "Rebuild complete", read: true, timestamp: "2 min" },
];

describe("NotificationCenter", () => {
  it("presents persistent unread/read history and emits item actions", () => {
    const onMarkRead = vi.fn(); const onAction = vi.fn(); const onDismiss = vi.fn();
    const { container } = render(<NotificationCenter items={items} onMarkRead={onMarkRead} onAction={onAction} onDismiss={onDismiss} />);
    expect(container.querySelectorAll(".aui-notification--unread")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Mark Linked source changed read" }));
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove Rebuild complete" }));
    expect(onMarkRead).toHaveBeenCalledWith("warn");
    expect(onAction).toHaveBeenCalledWith("warn");
    expect(onDismiss).toHaveBeenCalledWith("done");
  });

  it("clears history and renders a named empty state", () => {
    const onClear = vi.fn();
    const { rerender } = render(<NotificationCenter items={items} onClear={onClear} />);
    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    expect(onClear).toHaveBeenCalled();
    rerender(<NotificationCenter items={[]} emptyMessage="History is empty" />);
    expect(screen.getByText("History is empty")).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Clear all" })).toBeNull();
  });
});
