import { useEffect, useRef, useState } from "react";
import type { InputHTMLAttributes, KeyboardEvent, PointerEvent } from "react";
import { parseNumberExpression } from "./number-expression";

export interface NumberFieldProps
  extends Omit<
    InputHTMLAttributes<HTMLInputElement>,
    "type" | "value" | "defaultValue" | "onChange" | "onInput" | "onBlur" | "min" | "max" | "step"
  > {
  value?: number | null;
  defaultValue?: number;
  min?: number;
  max?: number;
  step?: number;
  precision?: number;
  unit?: string;
  mixed?: boolean;
  invalid?: boolean;
  scrubLabel?: string;
  onValueChange?: (value: number | null) => void;
  onCommit?: (value: number) => void;
  onCancel?: (value: number | null) => void;
}

function clamp(value: number, min?: number, max?: number): number {
  return Math.min(max ?? Number.POSITIVE_INFINITY, Math.max(min ?? Number.NEGATIVE_INFINITY, value));
}

function formatValue(value: number | null | undefined, precision?: number): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "";
  return precision === undefined ? String(value) : value.toFixed(precision);
}

/** Numeric authoring input with expression commit, explicit units, stepping,
 * mixed values, and an optional drag-to-scrub handle. */
export function NumberField({
  value,
  defaultValue,
  min,
  max,
  step = 1,
  precision,
  unit,
  mixed = false,
  invalid: invalidProp = false,
  scrubLabel,
  onValueChange,
  onCommit,
  onCancel,
  className,
  disabled,
  readOnly,
  placeholder,
  onKeyDown,
  ...inputProps
}: NumberFieldProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const committedRef = useRef<number | null>(value ?? defaultValue ?? null);
  const [invalidDraft, setInvalidDraft] = useState(false);

  useEffect(() => {
    if (value === undefined || !inputRef.current) return;
    committedRef.current = value;
    inputRef.current.value = formatValue(value, precision);
    setInvalidDraft(false);
  }, [precision, value]);

  const parseDraft = (): number | null => {
    const parsed = parseNumberExpression(inputRef.current?.value ?? "");
    if (parsed === null || parsed < (min ?? -Infinity) || parsed > (max ?? Infinity)) {
      return null;
    }
    return parsed;
  };

  const writeValue = (next: number, commit: boolean) => {
    const bounded = clamp(next, min, max);
    if (inputRef.current) inputRef.current.value = formatValue(bounded, precision);
    setInvalidDraft(false);
    onValueChange?.(bounded);
    if (commit) {
      committedRef.current = bounded;
      onCommit?.(bounded);
    }
  };

  const commitDraft = () => {
    const next = parseDraft();
    if (next === null) {
      setInvalidDraft(true);
      onValueChange?.(null);
      return;
    }
    writeValue(next, true);
  };

  const cancelDraft = () => {
    if (inputRef.current) {
      inputRef.current.value = formatValue(committedRef.current, precision);
      inputRef.current.select();
    }
    setInvalidDraft(false);
    onValueChange?.(committedRef.current);
    onCancel?.(committedRef.current);
  };

  const stepBy = (direction: 1 | -1, event: KeyboardEvent<HTMLInputElement>) => {
    const current = parseDraft() ?? committedRef.current ?? 0;
    const multiplier = event.shiftKey ? 10 : event.altKey ? 0.1 : 1;
    writeValue(current + direction * step * multiplier, true);
  };

  const beginScrub = (event: PointerEvent<HTMLButtonElement>) => {
    if (disabled || readOnly) return;
    event.preventDefault();
    const startX = event.clientX;
    const startValue = parseDraft() ?? committedRef.current ?? 0;
    let latest = startValue;
    const onMove = (moveEvent: globalThis.PointerEvent) => {
      latest = clamp(startValue + (moveEvent.clientX - startX) * step, min, max);
      writeValue(latest, false);
    };
    const onUp = () => {
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      writeValue(latest, true);
      inputRef.current?.focus();
    };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp, { once: true });
  };

  const classes = ["aui-number-field"];
  if (invalidProp || invalidDraft) classes.push("aui-number-field--invalid");
  if (mixed) classes.push("aui-number-field--mixed");
  if (className) classes.push(className);

  return (
    <span className="aui-number-field-wrap">
      {scrubLabel ? (
        <button
          type="button"
          className="aui-number-field-scrub"
          aria-label={`Adjust ${scrubLabel}`}
          title={`Drag to adjust ${scrubLabel}`}
          disabled={disabled || readOnly}
          onPointerDown={beginScrub}
        >
          ↔
        </button>
      ) : null}
      <input
        {...inputProps}
        ref={inputRef}
        type="text"
        inputMode="decimal"
        className={classes.join(" ")}
        defaultValue={mixed ? "" : formatValue(value ?? defaultValue, precision)}
        placeholder={mixed ? "Mixed" : placeholder}
        disabled={disabled}
        readOnly={readOnly}
        aria-invalid={invalidProp || invalidDraft || undefined}
        onInput={() => {
          const parsed = parseDraft();
          setInvalidDraft(false);
          onValueChange?.(parsed);
        }}
        onBlur={commitDraft}
        onKeyDown={(event) => {
          onKeyDown?.(event);
          if (event.defaultPrevented) return;
          if (event.key === "Enter") {
            event.preventDefault();
            commitDraft();
          } else if (event.key === "Escape") {
            event.preventDefault();
            cancelDraft();
          } else if (event.key === "ArrowUp" || event.key === "ArrowDown") {
            event.preventDefault();
            stepBy(event.key === "ArrowUp" ? 1 : -1, event);
          }
        }}
      />
      {unit ? <span className="aui-number-field-unit" aria-hidden>{unit}</span> : null}
    </span>
  );
}
