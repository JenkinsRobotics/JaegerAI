import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CommandPalette } from "./CommandPalette";

const commands = [
  { id: "open", label: "Open document", category: "File", shortcut: "⌘O", recent: true },
  { id: "export", label: "Export document", category: "File", keywords: ["save output"], argument: { label: "File name", required: true, submitLabel: "Export" } },
  { id: "measure", label: "Measure selection", category: "Inspect", disabled: true, disabledReason: "Select two entities." },
  { id: "fit", label: "Fit view", category: "View" },
] as const;

describe("CommandPalette", () => {
  it("shows recents, categories, shortcuts, and disabled explanations", () => {
    render(<CommandPalette open commands={commands} onSelect={() => {}} onClose={() => {}} />);
    expect(screen.getByRole("region", { name: "Recent" })).not.toBeNull();
    expect(screen.getByText("⌘O")).not.toBeNull();
    expect(screen.getByText("Select two entities.")).not.toBeNull();
    expect(screen.getByRole("option", { name: /Measure selection/ }).getAttribute("aria-disabled")).toBe("true");
  });

  it("fuzzy-matches keywords and reports no results", () => {
    render(<CommandPalette open commands={commands} onSelect={() => {}} onClose={() => {}} emptyMessage="Nothing found" />);
    const search = screen.getByRole("combobox");
    fireEvent.change(search, { target: { value: "svot" } });
    expect(screen.getByRole("option", { name: /Export document/ })).not.toBeNull();
    fireEvent.change(search, { target: { value: "zzzz" } });
    expect(screen.getByText("Nothing found")).not.toBeNull();
  });

  it("navigates enabled commands with arrows and executes Enter", () => {
    const onSelect = vi.fn();
    const onClose = vi.fn();
    render(<CommandPalette open commands={commands} onSelect={onSelect} onClose={onClose} />);
    const search = screen.getByRole("combobox");
    fireEvent.keyDown(search, { key: "End" });
    fireEvent.keyDown(search, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("fit");
    expect(onClose).toHaveBeenCalled();
  });

  it("collects required command arguments and Escape returns to search", async () => {
    const onSelect = vi.fn();
    const firstRender = render(<CommandPalette open commands={commands} onSelect={onSelect} onClose={() => {}} />);
    fireEvent.click(screen.getByRole("option", { name: /Export document/ }));
    const argument = screen.getByRole("textbox", { name: "File name" });
    fireEvent.keyDown(argument, { key: "Enter" });
    expect(screen.getByRole("alert").textContent).toContain("required");
    fireEvent.change(argument, { target: { value: "assembly.step" } });
    fireEvent.keyDown(argument, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("export", "assembly.step");

    firstRender.unmount();
    render(<CommandPalette open commands={commands} onSelect={() => {}} onClose={() => {}} title="Second palette" />);
    fireEvent.click(screen.getByRole("option", { name: /Export document/ }));
    fireEvent.keyDown(screen.getByRole("textbox", { name: "File name" }), { key: "Escape" });
    await waitFor(() => expect(screen.getByRole("combobox")).not.toBeNull());
  });

  it("closes on Escape and returns focus to the opener", async () => {
    const onClose = vi.fn();
    const { rerender } = render(<><button>Open commands</button><CommandPalette open={false} commands={commands} onSelect={() => {}} onClose={onClose} /></>);
    const opener = screen.getByRole("button", { name: "Open commands" });
    opener.focus();
    rerender(<><button>Open commands</button><CommandPalette open commands={commands} onSelect={() => {}} onClose={onClose} /></>);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("combobox")));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
    rerender(<><button>Open commands</button><CommandPalette open={false} commands={commands} onSelect={() => {}} onClose={onClose} /></>);
    await waitFor(() => expect(document.activeElement).toBe(opener));
  });
});
