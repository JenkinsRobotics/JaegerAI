import type { ReactNode } from "react";

export interface ErrorStateProps {
  title: ReactNode;
  description?: ReactNode;
  detail?: ReactNode;
  retryAction?: ReactNode;
  secondaryAction?: ReactNode;
  compact?: boolean;
  className?: string;
}

/** Actionable error surface for failed panels, dependencies, and operations. */
export function ErrorState({
  title,
  description,
  detail,
  retryAction,
  secondaryAction,
  compact,
  className,
}: ErrorStateProps) {
  const classes = ["aui-state", "aui-error-state"];
  if (compact) classes.push("aui-state--compact");
  if (className) classes.push(className);
  return (
    <section className={classes.join(" ")} role="alert">
      <div className="aui-state-icon" aria-hidden>!</div>
      <strong>{title}</strong>
      {description ? <p>{description}</p> : null}
      {detail ? <pre>{detail}</pre> : null}
      {retryAction || secondaryAction ? (
        <div className="aui-state-actions">{retryAction}{secondaryAction}</div>
      ) : null}
    </section>
  );
}
