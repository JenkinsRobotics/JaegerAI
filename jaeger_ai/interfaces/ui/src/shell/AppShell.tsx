/* Modified from AetherStudio studio/src/main.tsx Studio() (Apache-2.0, ece0209):
 * the aside.studio-sidebar + div.studio-body > main.studio-content layout,
 * reduced to slots: top / primary / sections / footer, and the main content.
 * Web/dev renders it as a floating rounded window on a backdrop; the native
 * macOS host (html[data-jaeger-host="macos"]) fills its window edge to edge. */
import type { ReactNode } from "react";

interface AppShellProps {
  /** Sidebar header: traffic-light band, search and + (window drag region). */
  top: ReactNode;
  /** Pinned supervisor + specialist list. */
  primary: ReactNode;
  /** Secondary entries (Tasks). */
  sections?: ReactNode;
  /** User avatar, Connect apps. */
  footer: ReactNode;
  children: ReactNode;
}

export function AppShell({ top, primary, sections, footer, children }: AppShellProps) {
  return (
    <div className="jg-desktop aether-home-theme">
      <div className="jg-shell">
        <aside className="jg-shell__sidebar" aria-label="Agents">
          <div className="jg-shell__top">{top}</div>
          <div className="jg-shell__primary">{primary}{sections}</div>
          <div className="jg-shell__footer">{footer}</div>
        </aside>
        <div className="jg-shell__body">
          <main className="jg-shell__content">{children}</main>
        </div>
      </div>
    </div>
  );
}
