import type { ReactNode } from "react";
import "./widget-card.css";

export type WidgetCardState = "ready" | "empty" | "loading" | "error";

export interface WidgetCardProps {
  title: string;
  value?: ReactNode;
  status?: ReactNode;
  trace?: ReactNode;
  actions?: ReactNode;
  state?: WidgetCardState;
  message?: string;
  children?: ReactNode;
}

/** Presentational card only: callers own data, actions, and any trace. */
export function WidgetCard({ title, value, status, trace, actions, state = "ready", message, children }: WidgetCardProps) {
  return <section className="jg-widget-card" aria-label={title} aria-busy={state === "loading"} data-state={state}>
    <header className="jg-widget-card__head">
      <h3>{title}</h3>
      {state === "ready" && actions && <div className="jg-widget-card__actions">{actions}</div>}
    </header>
    {state === "ready" ? <>
      {(value !== undefined || status) && <div className="jg-widget-card__summary">
        {value !== undefined && <strong className="jg-widget-card__value">{value}</strong>}
        {status && <span className="jg-widget-card__status">{status}</span>}
      </div>}
      {trace && <div className="jg-widget-card__trace" aria-label={`${title} trace`}>{trace}</div>}
      {children && <div className="jg-widget-card__body">{children}</div>}
    </> : <p className="jg-widget-card__message" role={state === "error" ? "alert" : "status"}>
      {message ?? (state === "loading" ? "Loading…" : state === "empty" ? "No data yet" : "Unable to load")}
    </p>}
  </section>;
}
