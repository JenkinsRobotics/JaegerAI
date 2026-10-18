import { useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, PointerEvent, ReactNode } from "react";

export interface SplitPaneProps {
  primary: ReactNode;
  secondary: ReactNode;
  orientation?: "horizontal" | "vertical";
  primarySize?: number;
  defaultPrimarySize?: number;
  minPrimarySize?: number;
  maxPrimarySize?: number;
  collapsed?: boolean;
  defaultCollapsed?: boolean;
  collapseSide?: "primary" | "secondary";
  onResize?: (primarySize: number) => void;
  onCollapsedChange?: (collapsed: boolean) => void;
  separatorLabel?: string;
  className?: string;
  style?: CSSProperties;
}

export function SplitPane({
  primary,
  secondary,
  orientation = "horizontal",
  primarySize,
  defaultPrimarySize = 280,
  minPrimarySize = 120,
  maxPrimarySize = 720,
  collapsed,
  defaultCollapsed = false,
  collapseSide = "secondary",
  onResize,
  onCollapsedChange,
  separatorLabel = "Resize panels",
  className,
  style,
}: SplitPaneProps) {
  const [internalSize, setInternalSize] = useState(defaultPrimarySize);
  const [internalCollapsed, setInternalCollapsed] = useState(defaultCollapsed);
  const containerRef = useRef<HTMLDivElement>(null);
  const size = primarySize ?? internalSize;
  const isCollapsed = collapsed ?? internalCollapsed;
  const clamp = (value: number) => Math.min(maxPrimarySize, Math.max(minPrimarySize, value));
  const resize = (value: number) => {
    const next = clamp(value);
    if (primarySize === undefined) setInternalSize(next);
    onResize?.(next);
  };
  const setCollapsed = (value: boolean) => {
    if (collapsed === undefined) setInternalCollapsed(value);
    onCollapsedChange?.(value);
  };
  const beginResize = (event: PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const startCoordinate = orientation === "horizontal" ? event.clientX : event.clientY;
    const startSize = size;
    const move = (moveEvent: globalThis.PointerEvent) => {
      const coordinate = orientation === "horizontal" ? moveEvent.clientX : moveEvent.clientY;
      resize(startSize + coordinate - startCoordinate);
    };
    const finish = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", finish);
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", finish);
  };
  const onSeparatorKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const decrement = orientation === "horizontal" ? "ArrowLeft" : "ArrowUp";
    const increment = orientation === "horizontal" ? "ArrowRight" : "ArrowDown";
    const step = event.shiftKey ? 50 : 10;
    if (event.key === decrement) resize(size - step);
    else if (event.key === increment) resize(size + step);
    else if (event.key === "Home") setCollapsed(true);
    else if (event.key === "End") {
      setCollapsed(false);
      resize(maxPrimarySize);
    } else if (event.key === "Enter") setCollapsed(!isCollapsed);
    else return;
    event.preventDefault();
  };

  const primaryCollapsed = isCollapsed && collapseSide === "primary";
  const secondaryCollapsed = isCollapsed && collapseSide === "secondary";
  const tracks = primaryCollapsed
    ? "0px 5px minmax(0, 1fr)"
    : secondaryCollapsed
      ? "minmax(0, 1fr) 5px 0px"
      : `${size}px 5px minmax(0, 1fr)`;
  const paneStyle = orientation === "horizontal"
    ? { gridTemplateColumns: tracks }
    : { gridTemplateRows: tracks };
  return (
    <div
      ref={containerRef}
      className={["aui-split-pane", `aui-split-pane--${orientation}`, className].filter(Boolean).join(" ")}
      style={{ ...style, ...paneStyle }}
    >
      <div className="aui-split-pane-primary" hidden={primaryCollapsed}>{primary}</div>
      <div
        className="aui-split-pane-separator"
        role="separator"
        aria-label={separatorLabel}
        aria-orientation={orientation === "horizontal" ? "vertical" : "horizontal"}
        aria-valuemin={minPrimarySize}
        aria-valuemax={maxPrimarySize}
        aria-valuenow={size}
        tabIndex={0}
        onPointerDown={beginResize}
        onDoubleClick={() => setCollapsed(!isCollapsed)}
        onKeyDown={onSeparatorKey}
      />
      <div className="aui-split-pane-secondary" hidden={secondaryCollapsed}>{secondary}</div>
      {secondaryCollapsed ? (
        <button className="aui-split-pane-restore" type="button" onClick={() => setCollapsed(false)}>Restore panel</button>
      ) : null}
    </div>
  );
}
