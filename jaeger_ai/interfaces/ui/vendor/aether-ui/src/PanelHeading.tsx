import type { ReactNode } from "react";

export function PanelHeading({
  children,
  actions,
}: {
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="aui-panel-heading">
      <span>{children}</span>
      {actions ? <span>{actions}</span> : null}
    </div>
  );
}
