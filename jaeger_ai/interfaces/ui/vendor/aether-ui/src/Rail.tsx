import type {
  ButtonHTMLAttributes,
  HTMLAttributes,
  ReactNode,
} from "react";

/** The vertical icon rail beside a sidebar. */
export interface RailProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

export function Rail({ children, className, ...props }: RailProps) {
  return <div {...props} className={["aui-rail", className].filter(Boolean).join(" ")}>{children}</div>;
}

export interface RailButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  label: string;
  active?: boolean;
  children: ReactNode;
}

export function RailButton({ label, active, className, children, ...props }: RailButtonProps) {
  const classes = ["aui-rail-button"];
  if (active) classes.push("aui-rail-button--active");
  if (className) classes.push(className);
  return (
    <button
      {...props}
      type="button"
      className={classes.join(" ")}
      title={label}
      aria-label={label}
      aria-pressed={active ?? false}
    >
      {children}
    </button>
  );
}
