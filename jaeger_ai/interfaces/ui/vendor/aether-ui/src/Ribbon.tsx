import type { ComponentPropsWithoutRef, KeyboardEvent, ReactNode } from "react";

/** The horizontal tool ribbon strip (groups with captions).
 *  ←/→ move focus across enabled tools, spanning group boundaries. */
export function Ribbon({ children }: { children: ReactNode }) {
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    const tools = Array.from(
      event.currentTarget.querySelectorAll<HTMLButtonElement>(
        ".aui-ribbon-tool:not(:disabled)"
      )
    );
    const index = tools.indexOf(document.activeElement as HTMLButtonElement);
    if (index < 0) return;
    event.preventDefault();
    const step = event.key === "ArrowRight" ? 1 : -1;
    tools[(index + step + tools.length) % tools.length]?.focus();
  };
  return (
    <div className="aui-ribbon" role="toolbar" onKeyDown={onKeyDown}>
      {children}
    </div>
  );
}

export function RibbonGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="aui-ribbon-group">
      <div className="aui-ribbon-group-buttons">{children}</div>
      <div className="aui-ribbon-group-label">{label}</div>
    </div>
  );
}

export interface RibbonToolProps extends Omit<ComponentPropsWithoutRef<"button">, "onClick"> {
  icon: ReactNode;
  label: string;
  active?: boolean;
  disabled?: boolean;
  onClick?: () => void;
}

/** Icon-over-label ribbon tool button. */
export function RibbonTool({ icon, label, active, disabled, onClick, ...buttonProps }: RibbonToolProps) {
  const classes = ["aui-ribbon-tool"];
  if (active) classes.push("aui-ribbon-tool--active");
  return (
    <button
      {...buttonProps}
      type="button"
      className={classes.join(" ")}
      disabled={disabled}
      onClick={onClick}
    >
      <span className="aui-ribbon-tool-icon" aria-hidden>
        {icon}
      </span>
      {label}
    </button>
  );
}
