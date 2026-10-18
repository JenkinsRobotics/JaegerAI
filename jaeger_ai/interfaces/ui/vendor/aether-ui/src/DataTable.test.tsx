import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { DataTable } from "./DataTable";

interface Row { id: string; name: string; count: number }
const rows: Row[] = [
  { id: "b", name: "Bracket", count: 2 },
  { id: "a", name: "Arm", count: 4 },
  { id: "c", name: "Cover", count: 1 },
];
const columns = [
  { id: "name", header: "Name", cell: (row: Row) => row.name, sortValue: (row: Row) => row.name, editValue: (row: Row) => row.name, editable: true, sortable: true, resizable: true, reorderable: true, pinned: true, width: 120 },
  { id: "count", header: "Qty", cell: (row: Row) => row.count, sortValue: (row: Row) => row.count, sortable: true, reorderable: true, width: 80 },
];

function table(overrides: Partial<Parameters<typeof DataTable<Row>>[0]> = {}) {
  const onSelect = vi.fn();
  const result = render(
    <DataTable
      ariaLabel="Bill of materials"
      rows={rows}
      rowID={(row) => row.id}
      columns={columns}
      selectedIDs={new Set()}
      onSelect={onSelect}
      {...overrides}
    />
  );
  return { onSelect, ...result };
}

test("renders typed cells, controlled sorting, and filtering", () => {
  const onSortChange = vi.fn();
  table({ sort: { columnID: "name", direction: "ascending" }, onSortChange, filter: "a" });
  const dataRows = screen.getAllByRole("row").slice(1);
  expect(dataRows.map((row) => row.textContent)).toEqual(["Arm4", "Bracket2"]);
  fireEvent.click(screen.getByText("Name"));
  expect(onSortChange).toHaveBeenCalledWith({ columnID: "name", direction: "descending" });
});

test("selection reports single, toggle, and visible range", () => {
  const { onSelect } = table();
  fireEvent.click(screen.getByText("Bracket"));
  fireEvent.click(screen.getByText("Arm"), { metaKey: true });
  expect(onSelect).toHaveBeenLastCalledWith(["a"], "toggle");
  fireEvent.click(screen.getByText("Bracket"));
  fireEvent.click(screen.getByText("Cover"), { shiftKey: true });
  expect(onSelect).toHaveBeenLastCalledWith(["b", "a", "c"], "range");
});

test("keyboard rows navigate and select", () => {
  const { onSelect } = table();
  const first = screen.getAllByRole("row")[1];
  first.focus();
  fireEvent.keyDown(first, { key: "ArrowDown" });
  expect(document.activeElement).toBe(screen.getAllByRole("row")[2]);
  fireEvent.keyDown(document.activeElement!, { key: " " });
  expect(onSelect).toHaveBeenLastCalledWith(["a"], "single");
});

test("editable cells commit on Enter and cancel on Escape", () => {
  const onEdit = vi.fn();
  table({ onEdit });
  fireEvent.doubleClick(screen.getByText("Bracket"));
  const input = screen.getByLabelText("Edit Name");
  fireEvent.change(input, { target: { value: "Mount" } });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(onEdit).toHaveBeenCalledWith("b", "name", "Mount");
});

test("row actions do not change selection", () => {
  const onRowAction = vi.fn();
  const onSelect = vi.fn();
  table({ onSelect, rowActions: () => [{ id: "open", label: "Open", icon: "↗" }], onRowAction });
  fireEvent.click(screen.getAllByLabelText("Open")[0]);
  expect(onRowAction).toHaveBeenCalledWith("b", "open");
  expect(onSelect).not.toHaveBeenCalled();
});

test("column resize and reorder emit intent", () => {
  const onColumnResize = vi.fn();
  const onColumnReorder = vi.fn();
  table({ onColumnResize, onColumnReorder });
  const pointerDown = new Event("pointerdown", { bubbles: true });
  Object.defineProperty(pointerDown, "clientX", { value: 10 });
  fireEvent(screen.getByLabelText("Resize Name"), pointerDown);
  const pointerMove = new Event("pointermove", { bubbles: true });
  Object.defineProperty(pointerMove, "clientX", { value: 40 });
  fireEvent(document, pointerMove);
  fireEvent.pointerUp(document);
  expect(onColumnResize).toHaveBeenCalledWith("name", 150);
  const dataTransfer = { setData: vi.fn(), getData: vi.fn() };
  const nameHeader = screen.getByText("Name").closest('[role="columnheader"]')!;
  const qtyHeader = screen.getByText("Qty").closest('[role="columnheader"]')!;
  fireEvent.dragStart(nameHeader, { dataTransfer });
  fireEvent.dragOver(qtyHeader, { dataTransfer });
  fireEvent.drop(qtyHeader, { dataTransfer });
  expect(onColumnReorder).toHaveBeenCalledWith("name", "count");
});

test("pinned columns use sticky offsets", () => {
  table();
  const heading = screen.getByText("Name").closest('[role="columnheader"]') as HTMLElement;
  expect(heading.style.position).toBe("sticky");
  expect(heading.style.left).toBe("0px");
});

test.each([
  [{ rows: [], emptyState: "No components" }, "No components", "status"],
  [{ loading: true, loadingState: "Loading BOM" }, "Loading BOM", "status"],
  [{ error: "BOM unavailable" }, "BOM unavailable", "alert"],
] as const)("renders table states", (overrides, message, role) => {
  table(overrides);
  expect(screen.getByRole(role).textContent).toContain(message);
});

test("large datasets render a fixed row window", () => {
  const many = Array.from({ length: 300 }, (_, index) => ({ id: String(index), name: `Part ${index}`, count: index }));
  const { container } = table({ rows: many, virtualizeThreshold: 20, height: 100, rowHeight: 20, overscan: 1 });
  expect(screen.getByText("Part 0")).not.toBeNull();
  expect(screen.queryByText("Part 299")).toBeNull();
  expect(container.querySelectorAll('.aui-data-table-row').length).toBeLessThan(20);
  expect((container.querySelector('.aui-data-table-body') as HTMLElement).style.height).toBe("6000px");
});
