import type { ReactNode } from "react";

export interface EmptyStateProps {
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  primaryAction?: ReactNode;
  secondaryAction?: ReactNode;
  compact?: boolean;
  className?: string;
}

/** Reusable empty/new/no-results surface with optional recovery actions. */
export function EmptyState({
  title,
  description,
  icon,
  primaryAction,
  secondaryAction,
  compact,
  className,
}: EmptyStateProps) {
  const classes = ["aui-state", "aui-empty-state"];
  if (compact) classes.push("aui-state--compact");
  if (className) classes.push(className);
  return (
    <section className={classes.join(" ")} aria-label={typeof title === "string" ? title : undefined}>
      {icon ? <div className="aui-state-icon" aria-hidden>{icon}</div> : null}
      <strong>{title}</strong>
      {description ? <p>{description}</p> : null}
      {primaryAction || secondaryAction ? (
        <div className="aui-state-actions">{primaryAction}{secondaryAction}</div>
      ) : null}
    </section>
  );
}
