import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DocumentTabs } from "./DocumentTabs";

const tabs = [
  { id: "one", label: "Assembly", pinned: true },
  { id: "two", label: "Bracket", dirty: true },
  { id: "three", label: "Layout", preview: true },
  { id: "four", label: "Reference", disabled: true },
];

describe("DocumentTabs", () => {
  it("exposes active, dirty, pinned, preview, and close policy", () => {
    render(<DocumentTabs tabs={tabs} activeID="one" onSelect={() => {}} onClose={() => {}} />);
    expect(screen.getByRole("tab", { name: "Pinned Assembly" }).getAttribute("aria-selected")).toBe("true");
    expect((screen.getByRole("button", { name: "Close Assembly" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("tab", { name: "Bracket Unsaved changes" })).not.toBeNull();
  });

  it("navigates enabled tabs with arrows and Home/End", () => {
    const onSelect = vi.fn();
    render(<DocumentTabs tabs={tabs} activeID="one" onSelect={onSelect} />);
    fireEvent.keyDown(screen.getByRole("tab", { name: "Pinned Assembly" }), { key: "End" });
    expect(onSelect).toHaveBeenCalledWith("three");
  });

  it("emits close, pin, reorder, and split intent", () => {
    const onClose = vi.fn(); const onPinToggle = vi.fn(); const onReorder = vi.fn(); const onSplit = vi.fn();
    render(<DocumentTabs tabs={tabs} activeID="two" onSelect={() => {}} onClose={onClose} onPinToggle={onPinToggle} onReorder={onReorder} onSplit={onSplit} />);
    fireEvent.click(screen.getByRole("button", { name: "Close Bracket" }));
    fireEvent.click(screen.getByRole("button", { name: "Pin active document" }));
    expect(onClose).toHaveBeenCalledWith("two");
    expect(onPinToggle).toHaveBeenCalledWith("two", true);
    const source = screen.getByRole("tab", { name: "Pinned Assembly" }).parentElement!;
    const target = screen.getByRole("tab", { name: "Bracket Unsaved changes" }).parentElement!;
    fireEvent.dragStart(source, { dataTransfer: { setData: vi.fn() } });
    fireEvent.drop(target, { dataTransfer: { getData: () => "one" } });
    expect(onReorder).toHaveBeenCalledWith("one", "two");
    fireEvent.click(screen.getByRole("button", { name: "Split active document" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Split vertically" }));
    expect(onSplit).toHaveBeenCalledWith("two", "vertical");
  });

  it("keeps the active document visible and selects overflow tabs", () => {
    const onSelect = vi.fn();
    render(<DocumentTabs tabs={tabs} activeID="three" maxVisible={2} onSelect={onSelect} />);
    expect(screen.getByRole("tab", { name: "Layout" })).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "More documents" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Bracket" }));
    expect(onSelect).toHaveBeenCalledWith("two");
  });
});
