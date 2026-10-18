import { useMemo, useRef, useState } from "react";
import type {
  CSSProperties,
  DragEvent,
  KeyboardEvent,
  PointerEvent,
  ReactNode,
  UIEvent,
} from "react";

export interface DataTableColumn<Row> {
  id: string;
  header: string;
  cell: (row: Row) => ReactNode;
  sortValue?: (row: Row) => string | number | null | undefined;
  editValue?: (row: Row) => string;
  editable?: boolean;
  sortable?: boolean;
  resizable?: boolean;
  reorderable?: boolean;
  pinned?: boolean;
  width?: number;
  minWidth?: number;
  maxWidth?: number;
  align?: "start" | "center" | "end";
}

export interface DataTableSort {
  columnID: string;
  direction: "ascending" | "descending";
}

export interface DataTableRowAction {
  id: string;
  label: string;
  icon: ReactNode;
  disabled?: boolean;
}

export interface DataTableProps<Row> {
  rows: readonly Row[];
  rowID: (row: Row) => string;
  columns: readonly DataTableColumn<Row>[];
  selectedIDs: ReadonlySet<string>;
  onSelect: (
    ids: readonly string[],
    mode: "single" | "toggle" | "range"
  ) => void;
  ariaLabel: string;
  selectionMode?: "single" | "multiple";
  sort?: DataTableSort | null;
  onSortChange?: (sort: DataTableSort | null) => void;
  filter?: string;
  filterText?: (row: Row) => string;
  onEdit?: (rowID: string, columnID: string, value: string) => void;
  onColumnResize?: (columnID: string, width: number) => void;
  onColumnReorder?: (sourceID: string, targetID: string) => void;
  rowActions?: (row: Row) => readonly DataTableRowAction[];
  onRowAction?: (rowID: string, actionID: string) => void;
  onActivate?: (rowID: string) => void;
  emptyState?: ReactNode;
  loading?: boolean;
  loadingState?: ReactNode;
  error?: ReactNode;
  virtualizeThreshold?: number;
  height?: number;
  rowHeight?: number;
  overscan?: number;
  className?: string;
  style?: CSSProperties;
}

interface EditingCell {
  rowID: string;
  columnID: string;
}

function compareValues(
  left: string | number | null | undefined,
  right: string | number | null | undefined
) {
  if (left == null && right == null) return 0;
  if (left == null) return 1;
  if (right == null) return -1;
  return typeof left === "number" && typeof right === "number"
    ? left - right
    : String(left).localeCompare(String(right), undefined, {
        numeric: true,
        sensitivity: "base",
      });
}

/** Product-free table for BOMs, parameters, problems, and task surfaces. */
export function DataTable<Row>({
  rows,
  rowID,
  columns,
  selectedIDs,
  onSelect,
  ariaLabel,
  selectionMode = "multiple",
  sort,
  onSortChange,
  filter,
  filterText,
  onEdit,
  onColumnResize,
  onColumnReorder,
  rowActions,
  onRowAction,
  onActivate,
  emptyState,
  loading = false,
  loadingState,
  error,
  virtualizeThreshold = 100,
  height = 280,
  rowHeight = 32,
  overscan = 4,
  className,
  style,
}: DataTableProps<Row>) {
  const [widths, setWidths] = useState<Record<string, number>>(() =>
    Object.fromEntries(columns.map((column) => [column.id, column.width ?? 140]))
  );
  const [focusedID, setFocusedID] = useState<string | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [editing, setEditing] = useState<EditingCell | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const anchorRef = useRef<string | null>(null);
  const dragColumnRef = useRef<string | null>(null);
  const rowRefs = useRef(new Map<string, HTMLDivElement>());

  const displayedRows = useMemo(() => {
    const query = (filter ?? "").trim().toLocaleLowerCase();
    let result = query
      ? rows.filter((row) => {
          const value = filterText
            ? filterText(row)
            : columns.map((column) => column.sortValue?.(row) ?? "").join(" ");
          return value.toLocaleLowerCase().includes(query);
        })
      : [...rows];
    if (sort) {
      const column = columns.find((entry) => entry.id === sort.columnID);
      if (column?.sortValue) {
        result = [...result].sort((left, right) => {
          const order = compareValues(column.sortValue!(left), column.sortValue!(right));
          return sort.direction === "ascending" ? order : -order;
        });
      }
    }
    return result;
  }, [columns, filter, filterText, rows, sort]);

  const hasActions = Boolean(rowActions);
  const template = [
    ...columns.map((column) => `${widths[column.id] ?? column.width ?? 140}px`),
    ...(hasActions ? ["36px"] : []),
  ].join(" ");
  const pinnedOffsets = useMemo(() => {
    const offsets: Record<string, number> = {};
    let left = 0;
    for (const column of columns) {
      if (!column.pinned) continue;
      offsets[column.id] = left;
      left += widths[column.id] ?? column.width ?? 140;
    }
    return offsets;
  }, [columns, widths]);

  const virtualized = displayedRows.length >= virtualizeThreshold;
  const start = virtualized
    ? Math.max(0, Math.floor(scrollTop / rowHeight) - overscan)
    : 0;
  const end = virtualized
    ? Math.min(
        displayedRows.length,
        Math.ceil((scrollTop + height) / rowHeight) + overscan
      )
    : displayedRows.length;
  const visibleRows = displayedRows.slice(start, end);

  const selectRow = (
    row: Row,
    event: { metaKey: boolean; ctrlKey: boolean; shiftKey: boolean }
  ) => {
    const id = rowID(row);
    if (selectionMode === "multiple" && event.shiftKey && anchorRef.current) {
      const from = displayedRows.findIndex((entry) => rowID(entry) === anchorRef.current);
      const to = displayedRows.findIndex((entry) => rowID(entry) === id);
      if (from >= 0 && to >= 0) {
        const [rangeStart, rangeEnd] = from < to ? [from, to] : [to, from];
        onSelect(
          displayedRows.slice(rangeStart, rangeEnd + 1).map(rowID),
          "range"
        );
        return;
      }
    }
    anchorRef.current = id;
    onSelect(
      [id],
      selectionMode === "multiple" && (event.metaKey || event.ctrlKey)
        ? "toggle"
        : "single"
    );
  };

  const focusRow = (index: number) => {
    const row = displayedRows[index];
    if (!row) return;
    const id = rowID(row);
    setFocusedID(id);
    rowRefs.current.get(id)?.focus();
  };

  const handleRowKey = (
    event: KeyboardEvent<HTMLDivElement>,
    row: Row,
    index: number
  ) => {
    switch (event.key) {
      case "ArrowDown":
        focusRow(Math.min(displayedRows.length - 1, index + 1));
        break;
      case "ArrowUp":
        focusRow(Math.max(0, index - 1));
        break;
      case "Home":
        focusRow(0);
        break;
      case "End":
        focusRow(displayedRows.length - 1);
        break;
      case "Enter":
        if (selectedIDs.has(rowID(row))) onActivate?.(rowID(row));
        else selectRow(row, event);
        break;
      case " ":
        selectRow(row, event);
        break;
      default:
        return;
    }
    event.preventDefault();
  };

  const startResize = (
    event: PointerEvent<HTMLSpanElement>,
    column: DataTableColumn<Row>
  ) => {
    event.preventDefault();
    event.stopPropagation();
    const initialX = event.clientX;
    const initialWidth = widths[column.id] ?? column.width ?? 140;
    const move = (moveEvent: globalThis.PointerEvent) => {
      const next = Math.min(
        column.maxWidth ?? 600,
        Math.max(column.minWidth ?? 60, initialWidth + moveEvent.clientX - initialX)
      );
      setWidths((current) => ({ ...current, [column.id]: next }));
      onColumnResize?.(column.id, next);
    };
    const finish = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", finish);
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", finish);
  };

  const beginEdit = (row: Row, column: DataTableColumn<Row>) => {
    if (!column.editable || !onEdit) return;
    setEditing({ rowID: rowID(row), columnID: column.id });
    setEditDraft(
      column.editValue?.(row) ?? String(column.sortValue?.(row) ?? "")
    );
  };
  const commitEdit = () => {
    if (!editing) return;
    onEdit?.(editing.rowID, editing.columnID, editDraft);
    setEditing(null);
  };

  const classes = ["aui-data-table", className].filter(Boolean).join(" ");
  if (loading || error || displayedRows.length === 0) {
    return (
      <div className={classes} role="grid" aria-label={ariaLabel} aria-busy={loading || undefined} style={style}>
        <div className="aui-data-table-state" role={error ? "alert" : "status"}>
          {error ?? (loading ? loadingState ?? "Loading…" : emptyState ?? "No rows")}
        </div>
      </div>
    );
  }

  return (
    <div className={classes} role="grid" aria-label={ariaLabel} aria-rowcount={displayedRows.length + 1} style={style}>
      <div className="aui-data-table-scroll" style={virtualized ? { height } : undefined} onScroll={(event: UIEvent<HTMLDivElement>) => setScrollTop(event.currentTarget.scrollTop)}>
        <div className="aui-data-table-header" role="row" style={{ gridTemplateColumns: template }}>
          {columns.map((column) => {
            const activeSort = sort?.columnID === column.id ? sort.direction : undefined;
            const pinnedStyle: CSSProperties | undefined = column.pinned
              ? { position: "sticky", left: pinnedOffsets[column.id], zIndex: 3 }
              : undefined;
            return (
              <div
                key={column.id}
                className="aui-data-table-heading"
                role="columnheader"
                aria-sort={activeSort ?? "none"}
                draggable={Boolean(column.reorderable && onColumnReorder)}
                style={{ ...pinnedStyle, justifyContent: column.align ?? "start" }}
                onDragStart={(event: DragEvent<HTMLDivElement>) => {
                  dragColumnRef.current = column.id;
                  event.dataTransfer.setData("text/plain", column.id);
                }}
                onDragOver={(event) => {
                  if (dragColumnRef.current && dragColumnRef.current !== column.id) event.preventDefault();
                }}
                onDrop={(event) => {
                  event.preventDefault();
                  if (dragColumnRef.current && dragColumnRef.current !== column.id) {
                    onColumnReorder?.(dragColumnRef.current, column.id);
                  }
                  dragColumnRef.current = null;
                }}
              >
                <button
                  type="button"
                  disabled={!column.sortable}
                  onClick={() => {
                    if (!column.sortable) return;
                    onSortChange?.(
                      !activeSort
                        ? { columnID: column.id, direction: "ascending" }
                        : activeSort === "ascending"
                          ? { columnID: column.id, direction: "descending" }
                          : null
                    );
                  }}
                >
                  {column.header}
                  {activeSort ? <span aria-hidden="true">{activeSort === "ascending" ? "▲" : "▼"}</span> : null}
                </button>
                {column.resizable ? (
                  <span className="aui-data-table-resizer" role="separator" aria-label={`Resize ${column.header}`} onPointerDown={(event) => startResize(event, column)} />
                ) : null}
              </div>
            );
          })}
          {hasActions ? <div role="columnheader" aria-label="Row actions" /> : null}
        </div>
        <div className="aui-data-table-body" style={virtualized ? { height: displayedRows.length * rowHeight } : undefined}>
          {visibleRows.map((row, offset) => {
            const id = rowID(row);
            const index = start + offset;
            const selected = selectedIDs.has(id);
            const rowStyle: CSSProperties = {
              gridTemplateColumns: template,
              ...(virtualized
                ? { position: "absolute", top: index * rowHeight, left: 0, height: rowHeight }
                : null),
            };
            return (
              <div
                key={id}
                ref={(element) => {
                  if (element) rowRefs.current.set(id, element);
                  else rowRefs.current.delete(id);
                }}
                className={`aui-data-table-row${selected ? " aui-data-table-row--selected" : ""}`}
                role="row"
                aria-selected={selected}
                tabIndex={focusedID === id || (focusedID === null && index === 0) ? 0 : -1}
                style={rowStyle}
                onFocus={() => setFocusedID(id)}
                onClick={(event) => selectRow(row, event)}
                onDoubleClick={() => onActivate?.(id)}
                onKeyDown={(event) => handleRowKey(event, row, index)}
              >
                {columns.map((column) => {
                  const isEditing = editing?.rowID === id && editing.columnID === column.id;
                  const pinnedStyle: CSSProperties | undefined = column.pinned
                    ? { position: "sticky", left: pinnedOffsets[column.id], zIndex: 2 }
                    : undefined;
                  return (
                    <div
                      key={column.id}
                      className="aui-data-table-cell"
                      role="gridcell"
                      style={{ ...pinnedStyle, justifyContent: column.align ?? "start" }}
                      onDoubleClick={(event) => {
                        event.stopPropagation();
                        beginEdit(row, column);
                      }}
                    >
                      {isEditing ? (
                        <input
                          autoFocus
                          aria-label={`Edit ${column.header}`}
                          value={editDraft}
                          onChange={(event) => setEditDraft(event.target.value)}
                          onClick={(event) => event.stopPropagation()}
                          onBlur={commitEdit}
                          onKeyDown={(event) => {
                            event.stopPropagation();
                            if (event.key === "Enter") commitEdit();
                            if (event.key === "Escape") setEditing(null);
                          }}
                        />
                      ) : (
                        column.cell(row)
                      )}
                    </div>
                  );
                })}
                {hasActions ? (
                  <div className="aui-data-table-actions" role="gridcell">
                    {rowActions?.(row).map((action) => (
                      <button
                        key={action.id}
                        type="button"
                        aria-label={action.label}
                        title={action.label}
                        disabled={action.disabled}
                        onClick={(event) => {
                          event.stopPropagation();
                          onRowAction?.(id, action.id);
                        }}
                      >
                        {action.icon}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
