import type { ButtonHTMLAttributes, ReactNode } from "react";

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Accessible name; rendered as title + aria-label. */
  label: string;
  children: ReactNode;
}

/** A compact square icon command (header/toolbar affordance). */
export function IconButton({ label, children, className, ...rest }: IconButtonProps) {
  const classes = ["aui-icon-button"];
  if (className) classes.push(className);
  return (
    <button
      type="button"
      className={classes.join(" ")}
      title={label}
      aria-label={label}
      {...rest}
    >
      {children}
    </button>
  );
}
