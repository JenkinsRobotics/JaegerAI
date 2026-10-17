import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { Tree } from "./Tree";

const nodes = [
  {
    id: "group",
    label: "Group",
    children: [
      { id: "a", label: "Alpha" },
      { id: "b", label: "Beta", dimmed: true },
      { id: "c", label: "Gamma", disabled: true },
    ],
  },
  { id: "solo", label: "Solo" },
];

function renderTree(overrides: Partial<Parameters<typeof Tree>[0]> = {}) {
  const onSelect = vi.fn();
  const utils = render(
    <Tree nodes={nodes} selectedIDs={new Set()} onSelect={onSelect} {...overrides} />
  );
  return { onSelect, ...utils };
}

test("single click replaces, cmd toggles, shift range-selects visible order", () => {
  const { onSelect } = renderTree();
  fireEvent.click(screen.getByText("Alpha"));
  expect(onSelect).toHaveBeenLastCalledWith(["a"], "single");
  fireEvent.click(screen.getByText("Solo"), { metaKey: true });
  expect(onSelect).toHaveBeenLastCalledWith(["solo"], "toggle");
  // Range from the Alpha anchor to Solo spans the visible rows, skipping
  // the disabled row.
  fireEvent.click(screen.getByText("Alpha"));
  fireEvent.click(screen.getByText("Solo"), { shiftKey: true });
  expect(onSelect).toHaveBeenLastCalledWith(["a", "b", "solo"], "range");
});

test("disclosure collapses without selecting", () => {
  const { onSelect } = renderTree();
  fireEvent.click(screen.getByText("▾"));
  expect(screen.queryByText("Alpha")).toBeNull();
  expect(onSelect).not.toHaveBeenCalled();
});

test("controlled expansion follows expandedIDs and reports onToggle", () => {
  const onToggle = vi.fn();
  const { rerender } = render(
    <Tree
      nodes={nodes}
      selectedIDs={new Set()}
      onSelect={() => {}}
      expandedIDs={new Set()}
      onToggle={onToggle}
    />
  );
  expect(screen.queryByText("Alpha")).toBeNull();
  fireEvent.click(screen.getByText("▸"));
  expect(onToggle).toHaveBeenCalledWith("group", true);
  rerender(
    <Tree
      nodes={nodes}
      selectedIDs={new Set()}
      onSelect={() => {}}
      expandedIDs={new Set(["group"])}
      onToggle={onToggle}
    />
  );
  expect(screen.queryByText("Alpha")).not.toBeNull();
});

test("filter keeps matches and ancestors, reveals collapsed branches", () => {
  render(
    <Tree
      nodes={nodes}
      selectedIDs={new Set()}
      onSelect={() => {}}
      defaultCollapsedIDs={["group"]}
      filter="bet"
    />
  );
  expect(screen.queryByText("Beta")).not.toBeNull();
  expect(screen.queryByText("Group")).not.toBeNull(); // ancestor kept
  expect(screen.queryByText("Alpha")).toBeNull();
  expect(screen.queryByText("Solo")).toBeNull();
});

test("keyboard: arrows navigate, left collapses to parent, enter selects", () => {
  const { onSelect } = renderTree();
  const first = screen.getByText("Group").closest('[role="treeitem"]') as HTMLElement;
  first.focus();
  fireEvent.keyDown(first, { key: "ArrowDown" });
  expect(document.activeElement).toBe(
    screen.getByText("Alpha").closest('[role="treeitem"]')
  );
  fireEvent.keyDown(document.activeElement!, { key: "ArrowLeft" });
  expect(document.activeElement).toBe(first);
  fireEvent.keyDown(first, { key: "Enter" });
  expect(onSelect).toHaveBeenLastCalledWith(["group"], "single");
});

test("disabled rows cannot be selected", () => {
  const { onSelect } = renderTree();
  fireEvent.click(screen.getByText("Gamma"));
  expect(onSelect).not.toHaveBeenCalled();
});

test("trailing actions fire without changing selection", () => {
  const onAction = vi.fn();
  const onSelect = vi.fn();
  render(
    <Tree
      nodes={[
        {
          id: "x",
          label: "X",
          actions: [{ id: "hide", label: "Hide", icon: "👁" }],
        },
      ]}
      selectedIDs={new Set()}
      onSelect={onSelect}
      onAction={onAction}
    />
  );
  fireEvent.click(screen.getByLabelText("Hide"));
  expect(onAction).toHaveBeenCalledWith("x", "hide");
  expect(onSelect).not.toHaveBeenCalled();
});

test("activate on double-click and context menu reports position", () => {
  const onActivate = vi.fn();
  const onContextMenu = vi.fn();
  renderTree({ onActivate, onContextMenu });
  fireEvent.doubleClick(screen.getByText("Solo"));
  expect(onActivate).toHaveBeenCalledWith("solo");
  fireEvent.contextMenu(screen.getByText("Solo"), { clientX: 9, clientY: 11 });
  expect(onContextMenu).toHaveBeenCalledWith("solo", 9, 11);
});

test("empty state renders when no rows survive", () => {
  render(
    <Tree
      nodes={[]}
      selectedIDs={new Set()}
      onSelect={() => {}}
      emptyState="nothing here"
    />
  );
  expect(screen.getByText("nothing here")).not.toBeNull();
});

test("controlled inline rename commits Enter and cancels Escape", () => {
  const onRename = vi.fn();
  const onCancelRename = vi.fn();
  const { rerender } = renderTree({
    renamingID: "a",
    onRename,
    onCancelRename,
  });
  const input = screen.getByLabelText("Rename Alpha");
  fireEvent.change(input, { target: { value: "Bracket" } });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(onRename).toHaveBeenCalledWith("a", "Bracket");

  rerender(
    <Tree
      nodes={nodes}
      selectedIDs={new Set()}
      onSelect={() => {}}
      renamingID="b"
      onRename={onRename}
      onCancelRename={onCancelRename}
    />
  );
  fireEvent.keyDown(screen.getByLabelText("Rename Beta"), { key: "Escape" });
  expect(onCancelRename).toHaveBeenCalledWith("b");
});

test("drag reports before, inside, or after intent without mutating data", () => {
  const onMove = vi.fn();
  renderTree({ onMove });
  const source = screen.getByText("Alpha").closest('[role="treeitem"]') as HTMLElement;
  const target = screen.getByText("Solo").closest('[role="treeitem"]') as HTMLElement;
  target.getBoundingClientRect = () => ({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: 100,
    bottom: 30,
    width: 100,
    height: 30,
    toJSON: () => {},
  });
  const dataTransfer = {
    effectAllowed: "none",
    dropEffect: "none",
    setData: vi.fn(),
    getData: vi.fn(),
  };
  fireEvent.dragStart(source, { dataTransfer });
  fireEvent.dragOver(target, { dataTransfer, clientY: 15 });
  fireEvent.drop(target, { dataTransfer, clientY: 15 });
  expect(dataTransfer.setData).toHaveBeenCalledWith("text/plain", "a");
  expect(onMove).toHaveBeenCalledWith("a", "solo", "inside");
  expect(screen.getByText("Alpha")).not.toBeNull();
});

test("expanded branches expose loading and recoverable error child rows", () => {
  const onRetryChildren = vi.fn();
  render(
    <Tree
      nodes={[
        { id: "loading", label: "Loading branch", childrenLoading: true },
        { id: "failed", label: "Failed branch", childrenError: "Network unavailable" },
      ]}
      selectedIDs={new Set()}
      onSelect={() => {}}
      onRetryChildren={onRetryChildren}
    />
  );
  expect(screen.getByRole("status").textContent).toContain("Loading");
  expect(screen.getByRole("alert").textContent).toContain("Network unavailable");
  fireEvent.click(screen.getByText("Retry"));
  expect(onRetryChildren).toHaveBeenCalledWith("failed");
});

test("large visible hierarchies render a fixed-row window", () => {
  const many = Array.from({ length: 1500 }, (_, index) => ({
    id: `node-${index}`,
    label: `Node ${index}`,
  }));
  const { container } = render(
    <Tree
      nodes={many}
      selectedIDs={new Set()}
      onSelect={() => {}}
      virtualizeThreshold={10}
      height={100}
      rowHeight={20}
      overscan={1}
    />
  );
  expect(screen.getByText("Node 0")).not.toBeNull();
  expect(screen.queryByText("Node 1499")).toBeNull();
  expect(container.querySelectorAll('[role="treeitem"]').length).toBeLessThan(20);
  expect((container.querySelector(".aui-tree-window") as HTMLElement).style.height).toBe(
    "30000px"
  );
});

test("row className lands on the row element and pinned actions carry the pinned class", () => {
  const { container } = renderTree({
    nodes: [
      { id: "bar", label: "Rollback", className: "cad-rollback-row" },
      { id: "plane", label: "Top Plane", actions: [
        { id: "show", label: "Show Top Plane", icon: "eye", pinned: true },
        { id: "edit", label: "Edit Top Plane", icon: "pen" },
      ] },
    ],
  });
  const bar = container.querySelector(".cad-rollback-row");
  expect(bar?.getAttribute("role")).toBe("treeitem");
  const pinned = screen.getByLabelText("Show Top Plane");
  expect(pinned.className).toContain("aui-tree-action--pinned");
  expect(screen.getByLabelText("Edit Top Plane").className).toBe("aui-tree-action");
});
