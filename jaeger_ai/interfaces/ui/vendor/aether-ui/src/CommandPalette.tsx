import { createPortal } from "react-dom";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

export interface CommandPaletteArgument {
  label: string;
  placeholder?: string;
  submitLabel?: string;
  initialValue?: string;
  required?: boolean;
  help?: ReactNode;
}

export interface CommandPaletteCommand {
  id: string;
  label: string;
  category?: string;
  description?: string;
  keywords?: readonly string[];
  icon?: ReactNode;
  shortcut?: string;
  disabled?: boolean;
  disabledReason?: string;
  recent?: boolean;
  argument?: CommandPaletteArgument;
}

export interface CommandPaletteProps {
  open: boolean;
  commands: readonly CommandPaletteCommand[];
  onSelect: (id: string, argument?: string) => void;
  onClose: () => void;
  title?: string;
  placeholder?: string;
  emptyMessage?: string;
  recentLabel?: string;
  uncategorizedLabel?: string;
}

interface RankedCommand {
  command: CommandPaletteCommand;
  score: number;
  index: number;
}

function normalize(value: string): string {
  return value.toLocaleLowerCase().trim();
}

function fuzzyScore(command: CommandPaletteCommand, query: string): number | null {
  const needle = normalize(query);
  if (!needle) return 0;
  const label = normalize(command.label);
  const haystack = normalize([command.label, command.category, command.description, ...(command.keywords ?? [])].filter(Boolean).join(" "));
  if (label === needle) return 1000;
  if (label.startsWith(needle)) return 800 - label.length;
  const direct = haystack.indexOf(needle);
  if (direct >= 0) return 600 - direct - haystack.length / 100;
  let cursor = 0;
  let gaps = 0;
  for (const character of needle) {
    const found = haystack.indexOf(character, cursor);
    if (found < 0) return null;
    gaps += found - cursor;
    cursor = found + 1;
  }
  return 300 - gaps - haystack.length / 100;
}

function groupedCommands(
  ranked: readonly RankedCommand[],
  query: string,
  recentLabel: string,
  uncategorizedLabel: string,
): readonly { label: string; items: readonly RankedCommand[] }[] {
  const groups: { label: string; items: RankedCommand[] }[] = [];
  const add = (label: string, item: RankedCommand) => {
    let group = groups.find((candidate) => candidate.label === label);
    if (!group) {
      group = { label, items: [] };
      groups.push(group);
    }
    group.items.push(item);
  };
  if (!normalize(query)) {
    for (const item of ranked.filter(({ command }) => command.recent)) add(recentLabel, item);
    for (const item of ranked.filter(({ command }) => !command.recent)) add(item.command.category ?? uncategorizedLabel, item);
    return groups;
  }
  for (const item of ranked) add(item.command.category ?? uncategorizedLabel, item);
  return groups;
}

const FOCUSABLE = 'button, input, [href], [tabindex]:not([tabindex="-1"])';

/** Product-free command chooser. Applications supply command availability and
 * execution; the palette owns only discovery, navigation, and argument entry. */
export function CommandPalette({
  open,
  commands,
  onSelect,
  onClose,
  title = "Command palette",
  placeholder = "Search commands",
  emptyMessage = "No matching commands",
  recentLabel = "Recent",
  uncategorizedLabel = "Commands",
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [activeID, setActiveID] = useState<string | null>(null);
  const [pendingCommand, setPendingCommand] = useState<CommandPaletteCommand | null>(null);
  const [argument, setArgument] = useState("");
  const [argumentError, setArgumentError] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const argumentRef = useRef<HTMLInputElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const listID = useId();

  const ranked = useMemo(() => commands
    .map((command, index) => ({ command, score: fuzzyScore(command, query), index }))
    .filter((item): item is RankedCommand => item.score !== null)
    .sort((a, b) => b.score - a.score || a.index - b.index), [commands, query]);
  const groups = groupedCommands(ranked, query, recentLabel, uncategorizedLabel);
  const displayed = groups.flatMap((group) => group.items);
  const enabled = displayed.filter(({ command }) => !command.disabled);

  useEffect(() => {
    if (!open) return;
    openerRef.current = document.activeElement as HTMLElement | null;
    setQuery("");
    setPendingCommand(null);
    setArgument("");
    setArgumentError(false);
    queueMicrotask(() => searchRef.current?.focus());
    return () => {
      openerRef.current?.focus?.();
      openerRef.current = null;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const first = enabled[0]?.command.id ?? null;
    if (!activeID || !enabled.some(({ command }) => command.id === activeID)) setActiveID(first);
  }, [activeID, enabled, open]);

  useEffect(() => {
    if (pendingCommand) queueMicrotask(() => argumentRef.current?.focus());
  }, [pendingCommand]);

  useEffect(() => {
    if (!open) return;
    const onDocumentKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        if (pendingCommand) {
          setPendingCommand(null);
          setArgumentError(false);
          queueMicrotask(() => searchRef.current?.focus());
        } else onClose();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((element) => !element.hasAttribute("disabled"));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const current = document.activeElement;
      if (event.shiftKey && (current === first || !dialogRef.current.contains(current))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (current === last || !dialogRef.current.contains(current))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onDocumentKeyDown, true);
    return () => document.removeEventListener("keydown", onDocumentKeyDown, true);
  }, [onClose, open, pendingCommand]);

  const choose = (command: CommandPaletteCommand) => {
    if (command.disabled) return;
    if (command.argument) {
      setPendingCommand(command);
      setArgument(command.argument.initialValue ?? "");
      setArgumentError(false);
      return;
    }
    onSelect(command.id);
    onClose();
  };
  const submitArgument = () => {
    if (!pendingCommand?.argument) return;
    const next = argument.trim();
    if (pendingCommand.argument.required && !next) {
      setArgumentError(true);
      return;
    }
    onSelect(pendingCommand.id, next);
    onClose();
  };
  const move = (event: KeyboardEvent<HTMLInputElement>) => {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    if (enabled.length === 0) return;
    const current = enabled.findIndex(({ command }) => command.id === activeID);
    let next = 0;
    if (event.key === "End") next = enabled.length - 1;
    else if (event.key === "ArrowUp") next = current <= 0 ? enabled.length - 1 : current - 1;
    else if (event.key === "ArrowDown") next = current < 0 || current === enabled.length - 1 ? 0 : current + 1;
    setActiveID(enabled[next]?.command.id ?? null);
  };

  if (!open || typeof document === "undefined") return null;
  return createPortal(
    <div className="aui-command-palette-scrim" onPointerDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div ref={dialogRef} className="aui-command-palette" role="dialog" aria-modal="true" aria-label={title}>
        {pendingCommand?.argument ? <>
          <header>
            <button type="button" className="aui-command-palette-back" onClick={() => { setPendingCommand(null); setArgumentError(false); queueMicrotask(() => searchRef.current?.focus()); }} aria-label="Back to commands">‹</button>
            <div><strong>{pendingCommand.label}</strong><span>{pendingCommand.argument.label}</span></div>
            <button type="button" className="aui-command-palette-close" onClick={onClose} aria-label="Close">×</button>
          </header>
          <div className="aui-command-palette-argument">
            <input
              ref={argumentRef}
              aria-label={pendingCommand.argument.label}
              placeholder={pendingCommand.argument.placeholder}
              value={argument}
              aria-invalid={argumentError || undefined}
              onChange={(event) => { setArgument(event.target.value); setArgumentError(false); }}
              onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); submitArgument(); } }}
            />
            {pendingCommand.argument.help ? <div className="aui-field-help">{pendingCommand.argument.help}</div> : null}
            {argumentError ? <div className="aui-field-error" role="alert">A value is required.</div> : null}
            <button type="button" className="aui-button aui-button--primary" onClick={submitArgument}>{pendingCommand.argument.submitLabel ?? "Run"}</button>
          </div>
        </> : <>
          <div className="aui-command-palette-search">
            <span aria-hidden>⌕</span>
            <input
              ref={searchRef}
              role="combobox"
              aria-label={placeholder}
              aria-controls={listID}
              aria-expanded="true"
              aria-autocomplete="list"
              aria-activedescendant={activeID ? `${listID}-${activeID}` : undefined}
              placeholder={placeholder}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                move(event);
                if (event.key === "Enter") {
                  event.preventDefault();
                  const command = enabled.find(({ command: candidate }) => candidate.id === activeID)?.command;
                  if (command) choose(command);
                }
              }}
            />
            <kbd>Esc</kbd>
          </div>
          <div id={listID} className="aui-command-palette-list" role="listbox" aria-label="Commands">
            {groups.length === 0 ? <div className="aui-command-palette-empty">{emptyMessage}</div> : groups.map((group) => <section key={group.label} aria-label={group.label}>
              <h3>{group.label}</h3>
              {group.items.map(({ command }) => <button
                key={command.id}
                id={`${listID}-${command.id}`}
                type="button"
                role="option"
                aria-selected={activeID === command.id}
                aria-disabled={command.disabled || undefined}
                className="aui-command-palette-item"
                title={command.disabled ? command.disabledReason : undefined}
                onPointerMove={() => { if (!command.disabled) setActiveID(command.id); }}
                onClick={() => choose(command)}
              >
                <span className="aui-command-palette-icon" aria-hidden>{command.icon ?? ""}</span>
                <span className="aui-command-palette-copy"><strong>{command.label}</strong>{command.disabled && command.disabledReason ? <small>{command.disabledReason}</small> : command.description ? <small>{command.description}</small> : null}</span>
                {command.shortcut ? <kbd>{command.shortcut}</kbd> : null}
                {command.argument ? <span aria-hidden>›</span> : null}
              </button>)}
            </section>)}
          </div>
          <footer><span>↑↓ Navigate</span><span>↵ Run</span><span>Esc Close</span></footer>
        </>}
      </div>
    </div>,
    document.body,
  );
}
