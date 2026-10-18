import { useEffect, useRef } from "react";
import type { InputHTMLAttributes, ReactNode } from "react";

export interface CheckboxProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label: ReactNode;
  description?: ReactNode;
  indeterminate?: boolean;
}

/** Checkbox with a consistent label/description and native form behavior. */
export function Checkbox({
  label,
  description,
  indeterminate = false,
  className,
  ...inputProps
}: CheckboxProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (inputRef.current) inputRef.current.indeterminate = indeterminate;
  }, [indeterminate]);
  const classes = ["aui-checkbox"];
  if (className) classes.push(className);
  return (
    <label className={classes.join(" ")}>
      <input
        {...inputProps}
        ref={inputRef}
        type="checkbox"
        aria-checked={indeterminate ? "mixed" : inputProps.checked}
      />
      <span className="aui-checkbox-mark" aria-hidden>{indeterminate ? "−" : "✓"}</span>
      <span className="aui-checkbox-copy">
        <span className="aui-checkbox-label">{label}</span>
        {description ? <span className="aui-checkbox-description">{description}</span> : null}
      </span>
    </label>
  );
}
