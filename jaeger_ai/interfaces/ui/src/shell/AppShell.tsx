/* Modified from AetherStudio studio/src/main.tsx Studio() (Apache-2.0, ece0209):
 * the aside.studio-sidebar + div.studio-body > main.studio-content layout,
 * reduced to slots: top / primary / sections / footer, and the main content. */
import type { ReactNode } from "react";

interface AppShellProps {
  /** Sidebar header: search and + buttons (window drag region). */
  top: ReactNode;
  /** Pinned supervisor + specialist list. */
  primary: ReactNode;
  /** Secondary entries (Tasks). */
  sections?: ReactNode;
  /** User chip, Connect apps. */
  footer: ReactNode;
  children: ReactNode;
  tray?: ReactNode;
}

export function AppShell({ top, primary, sections, footer, children, tray }: AppShellProps) {
  return (
    <div className="jg-shell aether-home-theme">
      <aside className="jg-shell__sidebar" aria-label="Agents">
        <div className="jg-shell__top">{top}</div>
        <div className="jg-shell__primary">{primary}{sections}</div>
        <div className="jg-shell__footer">{footer}</div>
      </aside>
      <div className="jg-shell__body">
        <main className="jg-shell__content">{children}</main>
        {tray}
      </div>
    </div>
  );
}
