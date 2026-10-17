import { createContext, useContext, useState, type ReactNode } from "react";
import { AetherIcon } from "./AetherIcon";

/**
 * Universal collapsible sidebar frame (OneDrive-style): full navigation or an
 * icon-only rail, with a persistent per-sidebar preference. Owns only the
 * frame, toggle, and persistence — navigation content stays app-owned so this
 * never grows app semantics. Wrap collapsible text in <SidebarLabel>; icons
 * stay visible in the rail. Pass toggle="custom" and render <SidebarToggle />
 * to place the collapse control inside your own layout (e.g. a user row).
 */
const SidebarContext = createContext<{ collapsed: boolean; toggle: () => void; ariaLabel: string } | null>(null);

export function SidebarToggle() {
  const context = useContext(SidebarContext);
  if (!context) return null;
  return (
    <button
      type="button"
      className="aui-sidebar-toggle"
      aria-expanded={!context.collapsed}
      aria-label={context.collapsed ? `Expand ${context.ariaLabel}` : `Collapse ${context.ariaLabel}`}
      title={context.collapsed ? "Expand sidebar" : "Collapse sidebar"}
      onClick={context.toggle}
    >
      <AetherIcon name="sidebar" />
    </button>
  );
}

export function CollapsibleSidebar({ id, ariaLabel, className, children, footer, toggle = "default" }: {
  /** Stable per-sidebar key; the collapse preference persists per device. */
  id: string;
  ariaLabel: string;
  className?: string;
  children: ReactNode;
  footer?: ReactNode;
  /** "custom": the app renders <SidebarToggle /> inside its own layout. */
  toggle?: "default" | "custom";
}) {
  const storageKey = `aether-sidebar-${id}`;
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(storageKey) === "collapsed"; } catch { return false; }
  });
  const toggleCollapsed = () => {
    const next = !collapsed;
    setCollapsed(next);
    try { localStorage.setItem(storageKey, next ? "collapsed" : "expanded"); } catch { /* device preference only */ }
  };
  return (
    <SidebarContext.Provider value={{ collapsed, toggle: toggleCollapsed, ariaLabel }}>
      <aside
        className={`aui-sidebar${collapsed ? " aui-sidebar--collapsed" : ""}${className ? ` ${className}` : ""}`}
        aria-label={ariaLabel}
      >
        {toggle === "default" ? <SidebarToggle /> : null}
        <div className="aui-sidebar-body">{children}</div>
        {footer ? <div className="aui-sidebar-footer">{footer}</div> : null}
      </aside>
    </SidebarContext.Provider>
  );
}

/** Text that hides when the owning sidebar collapses to its icon rail. */
export function SidebarLabel({ children }: { children: ReactNode }) {
  return <span className="aui-sidebar-label">{children}</span>;
}
