import { useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

export interface RadioGroupOption {
  id: string;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
}

export interface RadioGroupProps {
  options: readonly RadioGroupOption[];
  value?: string;
  defaultValue?: string;
  onChange?: (id: string) => void;
  label: ReactNode;
  name?: string;
  orientation?: "horizontal" | "vertical";
  disabled?: boolean;
  error?: ReactNode;
  className?: string;
}

export function RadioGroup({ options, value, defaultValue, onChange, label, name, orientation = "vertical", disabled = false, error, className }: RadioGroupProps) {
  const [internal, setInternal] = useState(defaultValue ?? options.find((item) => !item.disabled)?.id ?? "");
  const selected = value ?? internal;
  const refs = useRef(new Map<string, HTMLInputElement>());
  const select = (id: string) => {
    if (value === undefined) setInternal(id);
    onChange?.(id);
  };
  const move = (event: KeyboardEvent<HTMLInputElement>, id: string) => {
    const enabled = options.filter((item) => !disabled && !item.disabled);
    const current = enabled.findIndex((item) => item.id === id);
    let next = current;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") next = (current + 1) % enabled.length;
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = (current - 1 + enabled.length) % enabled.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = enabled.length - 1;
    else return;
    event.preventDefault();
    const option = enabled[next];
    if (!option) return;
    select(option.id);
    refs.current.get(option.id)?.focus();
  };
  return <fieldset className={["aui-radio-group", `aui-radio-group--${orientation}`, className].filter(Boolean).join(" ")} disabled={disabled} aria-invalid={Boolean(error) || undefined}>
    <legend>{label}</legend>
    <div className="aui-radio-options">
      {options.map((option) => <label key={option.id} className="aui-radio-option">
        <input
          ref={(element) => {
            if (element) refs.current.set(option.id, element);
            else refs.current.delete(option.id);
          }}
          type="radio"
          name={name}
          value={option.id}
          checked={selected === option.id}
          disabled={option.disabled}
          onChange={() => select(option.id)}
          onKeyDown={(event) => move(event, option.id)}
        />
        <span className="aui-radio-mark" aria-hidden />
        <span><span className="aui-radio-label">{option.label}</span>{option.description ? <span className="aui-radio-description">{option.description}</span> : null}</span>
      </label>)}
    </div>
    {error ? <div className="aui-field-error" role="alert">{error}</div> : null}
  </fieldset>;
}
