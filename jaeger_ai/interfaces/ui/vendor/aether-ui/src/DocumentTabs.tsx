import { useRef } from "react";
import type { DragEvent, KeyboardEvent, ReactNode } from "react";
import { MenuButton } from "./Menu";

export interface DocumentTab {
  id: string;
  label: string;
  icon?: ReactNode;
  dirty?: boolean;
  pinned?: boolean;
  preview?: boolean;
  disabled?: boolean;
}

export type DocumentSplitDirection = "horizontal" | "vertical";

export interface DocumentTabsProps {
  tabs: readonly DocumentTab[];
  activeID: string;
  onSelect: (id: string) => void;
  onClose?: (id: string) => void;
  onPinToggle?: (id: string, pinned: boolean) => void;
  onReorder?: (sourceID: string, targetID: string) => void;
  onSplit?: (id: string, direction: DocumentSplitDirection) => void;
  maxVisible?: number;
  allowClosePinned?: boolean;
  ariaLabel?: string;
  className?: string;
}

/** Controlled document strip. Products own document lifecycle and split layout;
 * the widget emits stable tab IDs and presentation intent only. */
export function DocumentTabs({ tabs, activeID, onSelect, onClose, onPinToggle, onReorder, onSplit, maxVisible = Number.POSITIVE_INFINITY, allowClosePinned = false, ariaLabel = "Open documents", className }: DocumentTabsProps) {
  const refs = useRef(new Map<string, HTMLButtonElement>());
  const enabled = tabs.filter((tab) => !tab.disabled);
  const bounded = Math.max(1, Math.floor(maxVisible));
  const visible = tabs.length <= bounded ? [...tabs] : tabs.slice(0, bounded);
  if (!visible.some((tab) => tab.id === activeID)) {
    const active = tabs.find((tab) => tab.id === activeID);
    if (active) visible[visible.length - 1] = active;
  }
  const visibleIDs = new Set(visible.map((tab) => tab.id));
  const overflow = tabs.filter((tab) => !visibleIDs.has(tab.id));

  const key = (event: KeyboardEvent<HTMLButtonElement>, id: string) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const index = enabled.findIndex((tab) => tab.id === id);
    let next = 0;
    if (event.key === "End") next = enabled.length - 1;
    else if (event.key === "ArrowLeft") next = index <= 0 ? enabled.length - 1 : index - 1;
    else if (event.key === "ArrowRight") next = index < 0 || index === enabled.length - 1 ? 0 : index + 1;
    const tab = enabled[next];
    if (!tab) return;
    onSelect(tab.id);
    queueMicrotask(() => refs.current.get(tab.id)?.focus());
  };
  const drop = (event: DragEvent<HTMLDivElement>, targetID: string) => {
    event.preventDefault();
    const sourceID = event.dataTransfer.getData("application/x-aether-document-tab");
    if (sourceID && sourceID !== targetID) onReorder?.(sourceID, targetID);
  };

  return <div className={["aui-document-tabs", className].filter(Boolean).join(" ")}>
    <div className="aui-document-tab-list" role="tablist" aria-label={ariaLabel}>
      {visible.map((tab) => <div
        key={tab.id}
        className={["aui-document-tab", tab.id === activeID ? "aui-document-tab--active" : "", tab.preview ? "aui-document-tab--preview" : ""].filter(Boolean).join(" ")}
        draggable={Boolean(onReorder) && !tab.disabled}
        onDragStart={(event) => event.dataTransfer.setData("application/x-aether-document-tab", tab.id)}
        onDragOver={(event) => { if (onReorder) event.preventDefault(); }}
        onDrop={(event) => drop(event, tab.id)}
      >
        <button
          ref={(element) => { if (element) refs.current.set(tab.id, element); else refs.current.delete(tab.id); }}
          type="button"
          role="tab"
          aria-selected={tab.id === activeID}
          tabIndex={tab.id === activeID ? 0 : -1}
          disabled={tab.disabled}
          onClick={() => onSelect(tab.id)}
          onKeyDown={(event) => key(event, tab.id)}
        >
          {tab.pinned ? <span aria-label="Pinned">●</span> : tab.icon ? <span aria-hidden>{tab.icon}</span> : null}
          <span className="aui-document-tab-label">{tab.label}</span>
          {tab.dirty ? <span className="aui-document-tab-dirty" aria-label="Unsaved changes">●</span> : null}
        </button>
        {onClose && tab.id === activeID ? <button type="button" className="aui-document-tab-close" aria-label={`Close ${tab.label}`} disabled={tab.pinned && !allowClosePinned} title={tab.pinned && !allowClosePinned ? "Unpin before closing." : undefined} onClick={() => onClose(tab.id)}>×</button> : null}
      </div>)}
    </div>
    {overflow.length > 0 ? <MenuButton
      className="aui-document-tabs-overflow"
      label="More documents"
      items={overflow.map((tab) => ({ id: tab.id, label: tab.label, icon: tab.pinned ? "●" : tab.dirty ? "•" : undefined, disabled: tab.disabled }))}
      onSelect={onSelect}
    >+{overflow.length}</MenuButton> : null}
    {onPinToggle ? <button type="button" className="aui-document-tabs-action" aria-label={tabs.find((tab) => tab.id === activeID)?.pinned ? "Unpin active document" : "Pin active document"} onClick={() => { const tab = tabs.find((candidate) => candidate.id === activeID); if (tab) onPinToggle(tab.id, !tab.pinned); }}>⌖</button> : null}
    {onSplit ? <MenuButton
      className="aui-document-tabs-action"
      label="Split active document"
      items={[{ id: "horizontal", label: "Split horizontally", icon: "═" }, { id: "vertical", label: "Split vertically", icon: "║" }]}
      onSelect={(direction) => onSplit(activeID, direction as DocumentSplitDirection)}
    >▥</MenuButton> : null}
  </div>;
}
