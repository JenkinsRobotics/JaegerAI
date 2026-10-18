import { useRef } from "react";
import type { KeyboardEvent, ReactNode } from "react";

export interface TabDefinition {
  id: string;
  label: string;
  icon?: ReactNode;
  disabled?: boolean;
  title?: string;
}

export interface TabsProps {
  tabs: readonly TabDefinition[];
  activeID: string;
  onSelect: (id: string) => void;
}

/** Underlined tab strip (workspaces, documents). Keyboard: ←/→ move and
 *  select (selection follows focus), Home/End jump; roving tabindex. */
export function Tabs({ tabs, activeID, onSelect }: TabsProps) {
  const refs = useRef(new Map<string, HTMLButtonElement>());

  const enabledIndexes = tabs.flatMap((tab, index) => tab.disabled ? [] : [index]);

  const onKeyDown = (event: KeyboardEvent, index: number) => {
    const current = Math.max(0, enabledIndexes.indexOf(index));
    let nextIndex: number;
    switch (event.key) {
      case "ArrowRight":
        nextIndex = enabledIndexes[(current + 1) % enabledIndexes.length];
        break;
      case "ArrowLeft":
        nextIndex = enabledIndexes[(current - 1 + enabledIndexes.length) % enabledIndexes.length];
        break;
      case "Home":
        nextIndex = enabledIndexes[0];
        break;
      case "End":
        nextIndex = enabledIndexes[enabledIndexes.length - 1];
        break;
      default:
        return;
    }
    event.preventDefault();
    const id = tabs[nextIndex].id;
    onSelect(id);
    refs.current.get(id)?.focus();
  };

  return (
    <div className="aui-tabs" role="tablist">
      {tabs.map((tab, index) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-label={tab.label}
          aria-selected={tab.id === activeID}
          tabIndex={!tab.disabled && tab.id === activeID ? 0 : -1}
          disabled={tab.disabled}
          title={tab.title}
          ref={(el) => {
            if (el) refs.current.set(tab.id, el);
            else refs.current.delete(tab.id);
          }}
          className={
            tab.id === activeID ? "aui-tab aui-tab--active" : "aui-tab"
          }
          onClick={() => !tab.disabled && onSelect(tab.id)}
          onKeyDown={(event) => onKeyDown(event, index)}
        >
          {tab.icon ? <span className="aui-tab-icon" aria-hidden="true">{tab.icon}</span> : null}
          <span>{tab.label}</span>
        </button>
      ))}
    </div>
  );
}
