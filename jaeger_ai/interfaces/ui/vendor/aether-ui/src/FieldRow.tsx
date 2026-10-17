import type { ReactNode } from "react";

export interface FieldRowProps {
  label: ReactNode;
  htmlFor?: string;
  children: ReactNode;
  help?: ReactNode;
  error?: ReactNode;
  modified?: boolean;
  required?: boolean;
  onReset?: () => void;
  className?: string;
}

/** Standard property-editor row. The application supplies the editor and owns
 * transactions; FieldRow owns consistent labeling, help, error, and reset UI. */
export function FieldRow({
  label,
  htmlFor,
  children,
  help,
  error,
  modified,
  required,
  onReset,
  className,
}: FieldRowProps) {
  const classes = ["aui-field-row"];
  if (error) classes.push("aui-field-row--error");
  if (modified) classes.push("aui-field-row--modified");
  if (className) classes.push(className);
  return (
    <div className={classes.join(" ")}>
      <div className="aui-field-row-heading">
        <label htmlFor={htmlFor}>
          {modified ? <span className="aui-field-row-modified" aria-hidden title="Modified">•</span> : null}
          {label}
          {required ? <span aria-hidden> *</span> : null}
        </label>
        {onReset ? <button type="button" onClick={onReset}>Reset</button> : null}
      </div>
      <div className="aui-field-row-editor">{children}</div>
      {error ? <div className="aui-field-row-error" role="alert">{error}</div> : null}
      {!error && help ? <div className="aui-field-row-help">{help}</div> : null}
    </div>
  );
}
