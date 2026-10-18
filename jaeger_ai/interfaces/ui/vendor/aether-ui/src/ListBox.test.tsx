import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ListBox } from "./ListBox";

const items = [
  { id: "steel", label: "Steel", description: "Structural", group: "Metals" },
  { id: "aluminum", label: "Aluminum", group: "Metals", dimmed: true },
  { id: "locked", label: "Locked alloy", group: "Metals", disabled: true },
  { id: "abs", label: "ABS", group: "Polymers", badge: "New" },
];

function renderList(overrides: Partial<Parameters<typeof ListBox>[0]> = {}) {
  const onSelect = vi.fn();
  const result = render(
    <ListBox
      ariaLabel="Materials"
      items={items}
      selectedIDs={new Set()}
      onSelect={onSelect}
      selectionMode="multiple"
      {...overrides}
    />
  );
  return { onSelect, ...result };
}

test("renders semantic nonselectable collections without inert row selection", () => {
  const onAction = vi.fn();
  render(<ListBox ariaLabel="Read-only results" items={[{ id: "one", label: "Result", actions: [{ id: "show", label: "Show result", icon: "↗" }] }]} selectedIDs={new Set()} selectionMode="none" onAction={onAction} />);
  expect(screen.getByRole("list", { name: "Read-only results" })).not.toBeNull();
  expect(screen.getByRole("listitem").getAttribute("tabindex")).toBe("-1");
  fireEvent.click(screen.getByRole("listitem"));
  fireEvent.click(screen.getByRole("button", { name: "Show result" }));
  expect(onAction).toHaveBeenCalledWith("one", "show");
});

test("renders grouped item content and selection state", () => {
  renderList({ selectedIDs: new Set(["steel"]) });
  expect(screen.getByText("Metals")).not.toBeNull();
  expect(screen.getByText("Polymers")).not.toBeNull();
  expect(screen.getByText("Structural")).not.toBeNull();
  expect(screen.getByText("New")).not.toBeNull();
  expect(
    screen.getByRole("option", { name: /Steel/ }).getAttribute("aria-selected")
  ).toBe("true");
});

test("multiple selection reports single, toggle, and range modes", () => {
  const { onSelect } = renderList();
  fireEvent.click(screen.getByText("Steel"));
  expect(onSelect).toHaveBeenLastCalledWith(["steel"], "single");
  fireEvent.click(screen.getByText("Aluminum"), { metaKey: true });
  expect(onSelect).toHaveBeenLastCalledWith(["aluminum"], "toggle");
  fireEvent.click(screen.getByText("Steel"));
  fireEvent.click(screen.getByText("ABS"), { shiftKey: true });
  expect(onSelect).toHaveBeenLastCalledWith(
    ["steel", "aluminum", "abs"],
    "range"
  );
});

test("single selection ignores modifier toggle semantics", () => {
  const { onSelect } = renderList({ selectionMode: "single" });
  fireEvent.click(screen.getByText("ABS"), { metaKey: true });
  expect(onSelect).toHaveBeenCalledWith(["abs"], "single");
});

test("keyboard navigation skips disabled rows and type-ahead wraps", () => {
  renderList();
  const steel = screen.getByRole("option", { name: /Steel/ });
  steel.focus();
  fireEvent.keyDown(steel, { key: "ArrowDown" });
  expect(document.activeElement).toBe(
    screen.getByRole("option", { name: "Aluminum" })
  );
  fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
  expect(document.activeElement).toBe(screen.getByRole("option", { name: /ABS/ }));
  fireEvent.keyDown(document.activeElement!, { key: "s" });
  expect(document.activeElement).toBe(steel);
});

test("space selects while Enter activates an already selected row", () => {
  const onActivate = vi.fn();
  const { onSelect, rerender } = renderList({ onActivate });
  const steel = screen.getByRole("option", { name: /Steel/ });
  fireEvent.keyDown(steel, { key: " " });
  expect(onSelect).toHaveBeenLastCalledWith(["steel"], "single");
  rerender(
    <ListBox
      ariaLabel="Materials"
      items={items}
      selectedIDs={new Set(["steel"])}
      onSelect={onSelect}
      onActivate={onActivate}
    />
  );
  fireEvent.keyDown(screen.getByRole("option", { name: /Steel/ }), { key: "Enter" });
  expect(onActivate).toHaveBeenCalledWith("steel");
});

test("disabled rows do not select and actions do not change selection", () => {
  const onAction = vi.fn();
  const onSelect = vi.fn();
  render(
    <ListBox
      ariaLabel="Objects"
      items={[
        { id: "disabled", label: "Disabled", disabled: true },
        {
          id: "body",
          label: "Body",
          actions: [{ id: "hide", label: "Hide", icon: "◉" }],
        },
      ]}
      selectedIDs={new Set()}
      onSelect={onSelect}
      onAction={onAction}
    />
  );
  fireEvent.click(screen.getByText("Disabled"));
  fireEvent.click(screen.getByLabelText("Hide"));
  expect(onSelect).not.toHaveBeenCalled();
  expect(onAction).toHaveBeenCalledWith("body", "hide");
});

test("activation and context menu report the item and coordinates", () => {
  const onActivate = vi.fn();
  const onContextMenu = vi.fn();
  renderList({ onActivate, onContextMenu });
  fireEvent.doubleClick(screen.getByText("ABS"));
  expect(onActivate).toHaveBeenCalledWith("abs");
  fireEvent.contextMenu(screen.getByText("ABS"), { clientX: 7, clientY: 12 });
  expect(onContextMenu).toHaveBeenCalledWith("abs", 7, 12);
});

test.each([
  [{ items: [], emptyState: "Nothing here" }, "Nothing here", "status"],
  [{ loading: true, loadingState: "Fetching materials" }, "Fetching materials", "status"],
  [{ error: "Could not load materials" }, "Could not load materials", "alert"],
] as const)("renders collection states", (overrides, text, role) => {
  renderList(overrides);
  expect(screen.getByRole(role).textContent).toContain(text);
});

test("large collections render a window rather than every row", () => {
  const many = Array.from({ length: 200 }, (_, index) => ({
    id: `item-${index}`,
    label: `Item ${index}`,
  }));
  const { container } = render(
    <ListBox
      ariaLabel="Large collection"
      items={many}
      selectedIDs={new Set()}
      onSelect={() => {}}
      virtualizeThreshold={20}
      height={100}
      rowHeight={20}
      overscan={1}
    />
  );
  expect(screen.getByText("Item 0")).not.toBeNull();
  expect(screen.queryByText("Item 199")).toBeNull();
  expect(container.querySelectorAll('[role="option"]').length).toBeLessThan(20);
  expect(
    (container.querySelector(".aui-listbox-window") as HTMLElement).style.height
  ).toBe("4000px");
});
