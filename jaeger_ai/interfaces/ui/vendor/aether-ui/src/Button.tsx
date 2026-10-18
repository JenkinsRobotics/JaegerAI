import type { ButtonHTMLAttributes } from "react";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Accent-filled call-to-action variant. */
  primary?: boolean;
  /** Pressed/latched state (e.g. an armed tool). */
  active?: boolean;
}

/** The standard Aether push button. */
export function Button({ primary, active, className, ...rest }: ButtonProps) {
  const classes = ["aui-button"];
  if (primary) classes.push("aui-button--primary");
  if (active) classes.push("aui-button--active");
  if (className) classes.push(className);
  return <button type="button" className={classes.join(" ")} {...rest} />;
}
