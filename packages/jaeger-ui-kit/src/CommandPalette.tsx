/**
 * Global Cmd+K / Ctrl+K Command Palette (inspired by OpenHands command-menu, MIT).
 */

import { useEffect, useMemo, useRef, useState } from "react";

export interface CommandItem {
  id: string;
  label: string;
  group: string;
  shortcut?: string;
  onSelect: () => void;
}

export interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  items: CommandItem[];
}

export function CommandPalette({ open, onClose, items }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [activeIdx, setActiveIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIdx(0);
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (it) => it.label.toLowerCase().includes(q) || it.group.toLowerCase().includes(q),
    );
  }, [items, query]);

  if (!open) return null;

  return (
    <div className="jg-palette-backdrop" onClick={onClose} role="dialog" aria-modal="true" aria-label="Command palette">
      <div className="jg-palette-card" onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          className="jg-palette-input"
          value={query}
          placeholder="Type a command, tab, or action..."
          onChange={(e) => {
            setQuery(e.target.value);
            setActiveIdx(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") onClose();
            else if (e.key === "ArrowDown") {
              e.preventDefault();
              setActiveIdx((i) => Math.min(filtered.length - 1, i + 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActiveIdx((i) => Math.max(0, i - 1));
            } else if (e.key === "Enter" && filtered[activeIdx]) {
              e.preventDefault();
              filtered[activeIdx].onSelect();
              onClose();
            }
          }}
        />
        <div className="jg-palette-list" role="listbox">
          {filtered.length === 0 ? (
            <div className="jg-palette-empty">No matching commands</div>
          ) : (
            filtered.map((item, idx) => (
              <button
                key={item.id}
                type="button"
                role="option"
                aria-selected={idx === activeIdx}
                className={`jg-palette-row ${idx === activeIdx ? "is-active" : ""}`}
                onMouseEnter={() => setActiveIdx(idx)}
                onClick={() => {
                  item.onSelect();
                  onClose();
                }}
              >
                <span>
                  <span className="jg-palette-group">{item.group}</span>
                  {item.label}
                </span>
                {item.shortcut && <kbd className="jg-kbd">{item.shortcut}</kbd>}
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
