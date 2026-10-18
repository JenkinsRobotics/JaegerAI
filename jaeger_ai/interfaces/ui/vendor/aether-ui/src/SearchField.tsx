import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";

export interface SearchFieldScope {
  id: string;
  label: string;
}

export interface SearchFieldProps {
  id?: string;
  value?: string;
  defaultValue?: string;
  onQueryChange?: (query: string) => void;
  onSearch?: (query: string) => void;
  delayMilliseconds?: number;
  placeholder?: string;
  ariaLabel?: string;
  resultCount?: number;
  scopes?: readonly SearchFieldScope[];
  scopeID?: string;
  onScopeChange?: (scopeID: string) => void;
  disabled?: boolean;
  autoFocus?: boolean;
  inputRef?: { current: HTMLInputElement | null } | ((element: HTMLInputElement | null) => void);
  className?: string;
}

/** Shared collection search. Products retain matching semantics; this widget
 * owns query entry, delayed search intent, scope selection, and clear/status UI. */
export function SearchField({
  id,
  value,
  defaultValue = "",
  onQueryChange,
  onSearch,
  delayMilliseconds = 180,
  placeholder = "Search",
  ariaLabel = "Search",
  resultCount,
  scopes = [],
  scopeID,
  onScopeChange,
  disabled = false,
  autoFocus = false,
  inputRef,
  className,
}: SearchFieldProps) {
  const controlled = value !== undefined;
  const [internalValue, setInternalValue] = useState(defaultValue);
  const query = controlled ? value : internalValue;
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const firstControlledValue = useRef(true);

  const cancelPending = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
  };

  const scheduleSearch = (next: string) => {
    cancelPending();
    if (!onSearch) return;
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      onSearch(next);
    }, Math.max(0, delayMilliseconds));
  };

  const update = (next: string, immediate = false) => {
    if (!controlled) setInternalValue(next);
    onQueryChange?.(next);
    if (immediate) {
      cancelPending();
      onSearch?.(next);
    } else {
      scheduleSearch(next);
    }
  };

  useEffect(() => () => cancelPending(), []);
  useEffect(() => {
    if (!controlled) return;
    if (firstControlledValue.current) {
      firstControlledValue.current = false;
      return;
    }
    scheduleSearch(value);
  }, [controlled, value]);

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      cancelPending();
      onSearch?.(query);
      return;
    }
    if (event.key === "Escape" && query) {
      event.preventDefault();
      update("", true);
    }
  };

  const classes = ["aui-search-field", className].filter(Boolean).join(" ");
  const countLabel = resultCount === undefined
    ? null
    : `${resultCount.toLocaleString()} ${resultCount === 1 ? "result" : "results"}`;
  return <div className={classes} data-empty={query.length === 0 || undefined}>
    <span className="aui-search-field-icon" aria-hidden>⌕</span>
    {scopes.length > 0 ? <select
      className="aui-search-field-scope"
      aria-label={`${ariaLabel} scope`}
      value={scopeID ?? scopes[0]?.id}
      disabled={disabled}
      onChange={(event) => onScopeChange?.(event.target.value)}
    >
      {scopes.map((scope) => <option key={scope.id} value={scope.id}>{scope.label}</option>)}
    </select> : null}
    <input
      id={id}
      ref={(element) => {
        if (typeof inputRef === "function") inputRef(element);
        else if (inputRef) inputRef.current = element;
      }}
      type="search"
      aria-label={ariaLabel}
      value={query}
      placeholder={placeholder}
      disabled={disabled}
      autoFocus={autoFocus}
      onChange={(event) => update(event.target.value)}
      onKeyDown={onKeyDown}
    />
    {countLabel ? <output className="aui-search-field-count" aria-live="polite">{countLabel}</output> : null}
    {query ? <button type="button" className="aui-search-field-clear" aria-label={`Clear ${ariaLabel.toLocaleLowerCase()}`} disabled={disabled} onClick={() => update("", true)}>×</button> : null}
  </div>;
}
