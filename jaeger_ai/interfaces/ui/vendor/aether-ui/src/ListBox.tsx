import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type {
  CSSProperties,
  KeyboardEvent,
  ReactNode,
  UIEvent,
} from "react";

export interface ListBoxItem {
  id: string;
  label: string;
  description?: string;
  icon?: ReactNode;
  badge?: string;
  group?: string;
  disabled?: boolean;
  dimmed?: boolean;
  actions?: readonly { id: string; label: string; icon: ReactNode }[];
}

export interface ListBoxProps {
  items: readonly ListBoxItem[];
  selectedIDs: ReadonlySet<string>;
  onSelect?: (
    ids: readonly string[],
    mode: "single" | "toggle" | "range"
  ) => void;
  ariaLabel: string;
  selectionMode?: "none" | "single" | "multiple";
  onActivate?: (id: string) => void;
  onContextMenu?: (id: string, x: number, y: number) => void;
  onAction?: (itemID: string, actionID: string) => void;
  emptyState?: ReactNode;
  loading?: boolean;
  loadingState?: ReactNode;
  error?: ReactNode;
  /** Lists at or above this item count use fixed-row windowing. */
  virtualizeThreshold?: number;
  /** Scroll viewport height used when windowing. */
  height?: number;
  rowHeight?: number;
  overscan?: number;
  className?: string;
  style?: CSSProperties;
}

interface ItemRow {
  kind: "item";
  item: ListBoxItem;
  itemIndex: number;
  top: number;
  height: number;
}

interface GroupRow {
  kind: "group";
  label: string;
  top: number;
  height: number;
}

type VisualRow = ItemRow | GroupRow;

const GROUP_HEIGHT = 25;
const TYPEAHEAD_RESET_MS = 700;

/**
 * THE flat collection for Aether products. Product code supplies data and
 * commands; ListBox owns consistent selection, keyboard, action, and scalable
 * rendering behavior.
 */
export function ListBox({
  items,
  selectedIDs,
  onSelect,
  ariaLabel,
  selectionMode = "single",
  onActivate,
  onContextMenu,
  onAction,
  emptyState,
  loading = false,
  loadingState,
  error,
  virtualizeThreshold = 100,
  height = 240,
  rowHeight = 34,
  overscan = 4,
  className,
  style,
}: ListBoxProps) {
  const [focusedID, setFocusedID] = useState<string | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const anchorRef = useRef<string | null>(null);
  const rowRefs = useRef(new Map<string, HTMLDivElement>());
  const scrollerRef = useRef<HTMLDivElement>(null);
  const typeaheadRef = useRef("");
  const typeaheadTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const enabledItems = useMemo(
    () => items.filter((item) => !item.disabled),
    [items]
  );

  const visualRows = useMemo<VisualRow[]>(() => {
    const rows: VisualRow[] = [];
    let top = 0;
    let lastGroup: string | undefined;
    items.forEach((item, itemIndex) => {
      if (item.group && item.group !== lastGroup) {
        rows.push({
          kind: "group",
          label: item.group,
          top,
          height: GROUP_HEIGHT,
        });
        top += GROUP_HEIGHT;
      }
      lastGroup = item.group;
      rows.push({ kind: "item", item, itemIndex, top, height: rowHeight });
      top += rowHeight;
    });
    return rows;
  }, [items, rowHeight]);

  const totalHeight = visualRows.length
    ? visualRows[visualRows.length - 1].top + visualRows[visualRows.length - 1].height
    : 0;
  const virtualized = items.length >= virtualizeThreshold;
  const visibleRows = useMemo(() => {
    if (!virtualized) return visualRows;
    const buffer = overscan * rowHeight;
    const start = Math.max(0, scrollTop - buffer);
    const end = scrollTop + height + buffer;
    return visualRows.filter(
      (row) => row.top + row.height >= start && row.top <= end
    );
  }, [height, overscan, rowHeight, scrollTop, virtualized, visualRows]);

  useEffect(
    () => () => {
      if (typeaheadTimerRef.current) clearTimeout(typeaheadTimerRef.current);
    },
    []
  );

  useEffect(() => {
    if (focusedID && !items.some((item) => item.id === focusedID && !item.disabled)) {
      setFocusedID(null);
    }
  }, [focusedID, items]);

  const applySelect = useCallback(
    (
      item: ListBoxItem,
      event: { metaKey: boolean; ctrlKey: boolean; shiftKey: boolean }
    ) => {
      if (item.disabled || selectionMode === "none" || !onSelect) return;
      if (
        selectionMode === "multiple" &&
        event.shiftKey &&
        anchorRef.current
      ) {
        const from = items.findIndex((entry) => entry.id === anchorRef.current);
        const to = items.findIndex((entry) => entry.id === item.id);
        if (from >= 0 && to >= 0) {
          const [start, end] = from < to ? [from, to] : [to, from];
          onSelect(
            items
              .slice(start, end + 1)
              .filter((entry) => !entry.disabled)
              .map((entry) => entry.id),
            "range"
          );
          return;
        }
      }
      anchorRef.current = item.id;
      onSelect(
        [item.id],
        selectionMode === "multiple" && (event.metaKey || event.ctrlKey)
          ? "toggle"
          : "single"
      );
    },
    [items, onSelect, selectionMode]
  );

  const focusItem = useCallback(
    (item: ListBoxItem | undefined) => {
      if (!item) return;
      setFocusedID(item.id);
      const element = rowRefs.current.get(item.id);
      if (element) {
        element.focus();
        return;
      }
      if (!virtualized) return;
      const row = visualRows.find(
        (entry): entry is ItemRow =>
          entry.kind === "item" && entry.item.id === item.id
      );
      if (!row) return;
      scrollerRef.current?.scrollTo({
        top: Math.max(0, row.top - (height - row.height) / 2),
      });
      requestAnimationFrame(() => rowRefs.current.get(item.id)?.focus());
    },
    [height, virtualized, visualRows]
  );

  const handleTypeahead = useCallback(
    (key: string, currentID: string) => {
      typeaheadRef.current += key.toLocaleLowerCase();
      if (typeaheadTimerRef.current) clearTimeout(typeaheadTimerRef.current);
      typeaheadTimerRef.current = setTimeout(() => {
        typeaheadRef.current = "";
      }, TYPEAHEAD_RESET_MS);

      const currentIndex = enabledItems.findIndex((item) => item.id === currentID);
      const ordered = [
        ...enabledItems.slice(currentIndex + 1),
        ...enabledItems.slice(0, currentIndex + 1),
      ];
      const query = typeaheadRef.current;
      const match = ordered.find((item) =>
        item.label.toLocaleLowerCase().startsWith(query)
      );
      focusItem(match);
    },
    [enabledItems, focusItem]
  );

  const onKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>, item: ListBoxItem) => {
      const index = enabledItems.findIndex((entry) => entry.id === item.id);
      switch (event.key) {
        case "ArrowDown":
          focusItem(enabledItems[index + 1] ?? enabledItems[0]);
          break;
        case "ArrowUp":
          focusItem(enabledItems[index - 1] ?? enabledItems[enabledItems.length - 1]);
          break;
        case "Home":
          focusItem(enabledItems[0]);
          break;
        case "End":
          focusItem(enabledItems[enabledItems.length - 1]);
          break;
        case "Enter":
          if (selectedIDs.has(item.id) && onActivate) onActivate(item.id);
          else applySelect(item, event);
          break;
        case " ":
          applySelect(item, event);
          break;
        default:
          if (
            event.key.length === 1 &&
            !event.metaKey &&
            !event.ctrlKey &&
            !event.altKey
          ) {
            handleTypeahead(event.key, item.id);
            event.preventDefault();
          }
          return;
      }
      event.preventDefault();
    },
    [applySelect, enabledItems, focusItem, handleTypeahead, onActivate, selectedIDs]
  );

  const renderRow = (row: VisualRow) => {
    const virtualStyle: CSSProperties | undefined = virtualized
      ? { position: "absolute", top: row.top, left: 0, right: 0, height: row.height }
      : undefined;
    if (row.kind === "group") {
      return (
        <div
          key={`group-${row.label}-${row.top}`}
          className="aui-listbox-group"
          role="presentation"
          style={virtualStyle}
        >
          {row.label}
        </div>
      );
    }

    const { item } = row;
    const selected = selectedIDs.has(item.id);
    const classes = ["aui-listbox-option"];
    if (selected) classes.push("aui-listbox-option--selected");
    if (item.dimmed) classes.push("aui-listbox-option--dimmed");
    return (
      <div
        key={item.id}
        ref={(element) => {
          if (element) rowRefs.current.set(item.id, element);
          else rowRefs.current.delete(item.id);
        }}
        className={classes.join(" ")}
        role={selectionMode === "none" ? "listitem" : "option"}
        aria-selected={selectionMode === "none" ? undefined : selected}
        aria-disabled={item.disabled || undefined}
        tabIndex={
          selectionMode !== "none" && !item.disabled &&
          (focusedID === item.id ||
            (focusedID === null && enabledItems[0]?.id === item.id))
            ? 0
            : -1
        }
        style={virtualStyle}
        onFocus={() => { if (selectionMode !== "none") setFocusedID(item.id); }}
        onClick={(event) => { if (selectionMode !== "none") applySelect(item, event); }}
        onDoubleClick={() => !item.disabled && onActivate?.(item.id)}
        onContextMenu={(event) => {
          if (!onContextMenu || item.disabled) return;
          event.preventDefault();
          onContextMenu(item.id, event.clientX, event.clientY);
        }}
        onKeyDown={(event) => onKeyDown(event, item)}
      >
        <span className="aui-listbox-icon" aria-hidden="true">
          {item.icon}
        </span>
        <span className="aui-listbox-copy">
          <span className="aui-listbox-label">{item.label}</span>
          {item.description ? (
            <span className="aui-listbox-description">{item.description}</span>
          ) : null}
        </span>
        {item.badge ? <span className="aui-listbox-badge">{item.badge}</span> : null}
        {item.actions?.length ? (
          <span className="aui-listbox-actions">
            {item.actions.map((action) => (
              <button
                key={action.id}
                type="button"
                aria-label={action.label}
                title={action.label}
                tabIndex={selectionMode === "none" ? 0 : -1}
                disabled={item.disabled}
                onClick={(event) => {
                  event.stopPropagation();
                  onAction?.(item.id, action.id);
                }}
              >
                {action.icon}
              </button>
            ))}
          </span>
        ) : null}
      </div>
    );
  };

  const classes = ["aui-listbox", className].filter(Boolean).join(" ");
  const handleScroll = (event: UIEvent<HTMLDivElement>) => {
    if (virtualized) setScrollTop(event.currentTarget.scrollTop);
  };

  if (loading || error || items.length === 0) {
    return (
      <div
        className={classes}
        role={selectionMode === "none" ? "list" : "listbox"}
        aria-label={ariaLabel}
        aria-busy={loading || undefined}
        aria-multiselectable={selectionMode === "multiple" || undefined}
        style={style}
      >
        <div className="aui-listbox-state" role={error ? "alert" : "status"}>
          {error ?? (loading ? loadingState ?? "Loading…" : emptyState ?? "No items")}
        </div>
      </div>
    );
  }

  return (
    <div
      ref={scrollerRef}
      className={classes}
      role={selectionMode === "none" ? "list" : "listbox"}
      aria-label={ariaLabel}
      aria-multiselectable={selectionMode === "multiple" || undefined}
      style={{
        ...style,
        ...(virtualized ? { height, overflowY: "auto" } : null),
      }}
      onScroll={handleScroll}
    >
      <div
        className={virtualized ? "aui-listbox-window" : undefined}
        style={virtualized ? { height: totalHeight } : undefined}
      >
        {visibleRows.map(renderRow)}
      </div>
    </div>
  );
}
