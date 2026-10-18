import type { InputHTMLAttributes } from "react";

export interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Marks the value invalid (error border + aria-invalid). */
  invalid?: boolean;
  /** Unit suffix rendered inside the field (e.g. "mm", "deg", "s"). */
  unit?: string;
}

/** Single-line inset text input, optionally with a unit suffix. */
export function TextField({ invalid, unit, className, style, ...rest }: TextFieldProps) {
  const classes = ["aui-text-field"];
  if (invalid) classes.push("aui-text-field--invalid");
  if (className) classes.push(className);
  const input = (
    <input
      className={classes.join(" ")}
      aria-invalid={invalid || undefined}
      style={unit ? undefined : style}
      {...rest}
    />
  );
  if (!unit) return input;
  return (
    <span className="aui-text-field-wrap" style={style}>
      {input}
      <span className="aui-text-field-unit" aria-hidden>
        {unit}
      </span>
    </span>
  );
}
