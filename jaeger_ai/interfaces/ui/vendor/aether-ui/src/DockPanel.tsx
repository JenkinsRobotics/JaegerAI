import type { CSSProperties, ReactNode } from "react";
import { PanelHeading } from "./PanelHeading";

export interface DockPanelProps {
  title?: string;
  actions?: ReactNode;
  width?: number | string;
  children: ReactNode;
}

/**
 * A docked side panel: heading + scrollable body. Multi-panel docking
 * layout (drag/split) is the app shell's concern (see the UI framework
 * decision record: use an established docking library there).
 */
export function DockPanel({ title, actions, width, children }: DockPanelProps) {
  const style: CSSProperties | undefined =
    width === undefined ? undefined : { width, flex: "0 0 auto" };
  return (
    <div className="aui-dock-panel" style={style}>
      {title ? <PanelHeading actions={actions}>{title}</PanelHeading> : null}
      <div className="aui-dock-panel-body">{children}</div>
    </div>
  );
}
