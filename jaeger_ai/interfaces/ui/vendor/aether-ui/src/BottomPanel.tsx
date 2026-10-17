import { useRef } from "react";
import type { KeyboardEvent, ReactNode } from "react";

export interface BottomPanelTab {
  id: string;
  label: string;
  badge?: string | number;
  icon?: ReactNode;
  content: ReactNode;
}

export interface BottomPanelProps {
  tabs: readonly BottomPanelTab[];
  activeID: string;
  onSelect: (id: string) => void;
  collapsed?: boolean;
  onCollapsedChange?: (collapsed: boolean) => void;
  actions?: ReactNode;
  ariaLabel?: string;
}

export function BottomPanel({
  tabs,
  activeID,
  onSelect,
  collapsed = false,
  onCollapsedChange,
  actions,
  ariaLabel = "Bottom panel",
}: BottomPanelProps) {
  const refs = useRef(new Map<string, HTMLButtonElement>());
  const active = tabs.find((tab) => tab.id === activeID) ?? tabs[0];
  const move = (event: KeyboardEvent, index: number) => {
    let next: number;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    else return;
    event.preventDefault();
    onSelect(tabs[next].id);
    refs.current.get(tabs[next].id)?.focus();
  };
  if (!active) return null;
  return (
    <section className={`aui-bottom-panel${collapsed ? " aui-bottom-panel--collapsed" : ""}`} aria-label={ariaLabel}>
      <header className="aui-bottom-panel-header" onDoubleClick={() => onCollapsedChange?.(!collapsed)}>
        <div className="aui-bottom-panel-tabs" role="tablist" aria-label={`${ariaLabel} tabs`}>
          {tabs.map((tab, index) => (
            <button
              key={tab.id}
              ref={(element) => {
                if (element) refs.current.set(tab.id, element);
                else refs.current.delete(tab.id);
              }}
              id={`aui-bottom-tab-${tab.id}`}
              type="button"
              role="tab"
              aria-selected={tab.id === active.id}
              aria-controls={`aui-bottom-panel-${tab.id}`}
              tabIndex={tab.id === active.id ? 0 : -1}
              onClick={() => {
                onSelect(tab.id);
                if (collapsed) onCollapsedChange?.(false);
              }}
              onKeyDown={(event) => move(event, index)}
            >
              {tab.icon ? <span aria-hidden="true">{tab.icon}</span> : null}
              {tab.label}
              {tab.badge !== undefined ? <small>{tab.badge}</small> : null}
            </button>
          ))}
        </div>
        <div className="aui-bottom-panel-actions">
          {actions}
          <button type="button" aria-label={collapsed ? "Expand bottom panel" : "Collapse bottom panel"} onClick={() => onCollapsedChange?.(!collapsed)}>{collapsed ? "⌃" : "⌄"}</button>
        </div>
      </header>
      {!collapsed ? (
        <div className="aui-bottom-panel-content" id={`aui-bottom-panel-${active.id}`} role="tabpanel" aria-labelledby={`aui-bottom-tab-${active.id}`}>
          {active.content}
        </div>
      ) : null}
    </section>
  );
}
