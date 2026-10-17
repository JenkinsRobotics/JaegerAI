import type { SelectHTMLAttributes } from "react";

export interface SelectFieldOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface SelectFieldProps
  extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "children"> {
  options: readonly SelectFieldOption[];
  placeholder?: string;
  invalid?: boolean;
}

/** Native select semantics with the shared Aether field presentation. */
export function SelectField({
  options,
  placeholder,
  invalid,
  className,
  ...selectProps
}: SelectFieldProps) {
  const classes = ["aui-select-field"];
  if (invalid) classes.push("aui-select-field--invalid");
  if (className) classes.push(className);
  return (
    <span className="aui-select-field-wrap">
      <select
        {...selectProps}
        className={classes.join(" ")}
        aria-invalid={invalid || undefined}
      >
        {placeholder ? <option value="">{placeholder}</option> : null}
        {options.map((option) => (
          <option key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </option>
        ))}
      </select>
      <span className="aui-select-field-arrow" aria-hidden>⌄</span>
    </span>
  );
}
