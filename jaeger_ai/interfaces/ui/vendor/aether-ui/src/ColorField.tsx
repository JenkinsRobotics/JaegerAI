import { useEffect, useState } from "react";
import type { KeyboardEvent } from "react";

export interface ColorFieldProps {
  value?: string;
  defaultValue?: string;
  onChange?: (hex: string) => void;
  ariaLabel: string;
  disabled?: boolean;
  invalidMessage?: string;
  className?: string;
}

const validHex = (value: string) => /^#[0-9a-f]{6}$/i.test(value);

export function ColorField({ value, defaultValue = "#2b9cf3", onChange, ariaLabel, disabled = false, invalidMessage = "Enter a six-digit hex color.", className }: ColorFieldProps) {
  const initial = validHex(value ?? defaultValue) ? (value ?? defaultValue).toLowerCase() : "#2b9cf3";
  const [internal, setInternal] = useState(initial);
  const current = value ?? internal;
  const [draft, setDraft] = useState(current);
  const [invalid, setInvalid] = useState(false);
  useEffect(() => { setDraft(current); setInvalid(false); }, [current]);
  const commit = () => {
    if (!validHex(draft)) { setInvalid(true); return; }
    const next = draft.toLowerCase();
    setInvalid(false);
    setDraft(next);
    if (value === undefined) setInternal(next);
    onChange?.(next);
  };
  const choose = (next: string) => {
    setDraft(next);
    setInvalid(false);
    if (value === undefined) setInternal(next);
    onChange?.(next);
  };
  const key = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") { event.preventDefault(); commit(); }
    if (event.key === "Escape") { event.preventDefault(); setDraft(current); setInvalid(false); }
  };
  return <div className={["aui-color-field", className].filter(Boolean).join(" ")}>
    <input className="aui-color-field-picker" type="color" aria-label={`${ariaLabel} picker`} value={validHex(current) ? current : initial} disabled={disabled} onChange={(event) => choose(event.target.value)} />
    <input className="aui-color-field-text" aria-label={ariaLabel} value={draft} disabled={disabled} aria-invalid={invalid || undefined} onChange={(event) => setDraft(event.target.value)} onBlur={commit} onKeyDown={key} />
    {invalid ? <span className="aui-field-error" role="alert">{invalidMessage}</span> : null}
  </div>;
}
