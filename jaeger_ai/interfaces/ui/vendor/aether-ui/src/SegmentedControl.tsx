import { useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

export interface SegmentedControlOption {
  id: string;
  label: ReactNode;
  icon?: ReactNode;
  disabled?: boolean;
}

export interface SegmentedControlProps {
  options: readonly SegmentedControlOption[];
  value?: string;
  defaultValue?: string;
  onChange?: (id: string) => void;
  ariaLabel: string;
  disabled?: boolean;
  className?: string;
}

export function SegmentedControl({ options, value, defaultValue, onChange, ariaLabel, disabled = false, className }: SegmentedControlProps) {
  const [internal, setInternal] = useState(defaultValue ?? options.find((item) => !item.disabled)?.id ?? "");
  const selected = value ?? internal;
  const refs = useRef(new Map<string, HTMLButtonElement>());
  const select = (id: string) => {
    if (value === undefined) setInternal(id);
    onChange?.(id);
  };
  const move = (event: KeyboardEvent<HTMLButtonElement>, id: string) => {
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
  return <div className={["aui-segmented-control", className].filter(Boolean).join(" ")} role="radiogroup" aria-label={ariaLabel} aria-disabled={disabled || undefined}>
    {options.map((option) => <button
      key={option.id}
      ref={(element) => {
        if (element) refs.current.set(option.id, element);
        else refs.current.delete(option.id);
      }}
      type="button"
      role="radio"
      aria-checked={selected === option.id}
      tabIndex={selected === option.id ? 0 : -1}
      disabled={disabled || option.disabled}
      onClick={() => select(option.id)}
      onKeyDown={(event) => move(event, option.id)}
    >{option.icon ? <span aria-hidden>{option.icon}</span> : null}<span>{option.label}</span></button>)}
  </div>;
}
