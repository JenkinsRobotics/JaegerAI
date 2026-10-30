/**
 * WidgetFrame (Jenkins Robotics, 2026-10-29, original).
 *
 * The card shell every host uses. It owns the title, the observed-at stamp, the
 * tint treatment and the loading/error states, so a widget's `view()` only renders
 * content and cannot accidentally ship a fake value.
 *
 * Tint mapping (neutral names, same semantics as the platform guidance):
 *   full   → solid elevated surface
 *   tinted → translucent surface with the accent applied to the frame
 *   dimmed → desaturated, low-emphasis (lock-screen-like contexts)
 */
import type { ReactNode } from "react";
import { ErrorState } from "../../shell/ErrorState";
import { Skeleton } from "./Skeleton";
import type { WidgetSize, WidgetTint } from "../types";

const CLOCKS: Record<WidgetSize, string> = {
  sm: "wg-frame--sm",
  md: "wg-frame--md",
  lg: "wg-frame--lg",
  xl: "wg-frame--xl",
  inline: "wg-frame--inline",
  circle: "wg-frame--circle",
  rect: "wg-frame--rect",
};

export interface WidgetFrameProps {
  title: string;
  size: WidgetSize;
  tint: WidgetTint;
  status: "loading" | "ready" | "error";
  error?: string;
  /** ms timestamp of the data the frame is showing. Omitted while loading. */
  observedAt?: number;
  onRetry?: () => void;
  actions?: ReactNode;
  children: ReactNode;
}

/** Compact relative stamp: "as of 12s" reads honestly without a clock dependency. */
export function observedLabel(observedAt: number, now = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - observedAt) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.round(minutes / 60)}h ago`;
}

export function WidgetFrame({
  title,
  size,
  tint,
  status,
  error,
  observedAt,
  onRetry,
  actions,
  children,
}: WidgetFrameProps) {
  return (
    <section
      className={`wg-frame ${CLOCKS[size]} wg-frame--${tint}`}
      data-widget-status={status}
      aria-label={title}
    >
      <header className="wg-frame__head">
        <span className="wg-frame__title">{title}</span>
        {actions && <span className="wg-frame__actions">{actions}</span>}
      </header>

      <div className="wg-frame__body">
        {status === "loading" && <Skeleton lines={size === "sm" ? 2 : 3} />}
        {status === "error" && (
          <ErrorState compact title="Couldn't load" error={error ?? "Unknown error"} onRetry={onRetry} />
        )}
        {status === "ready" && children}
      </div>

      {status === "ready" && observedAt !== undefined && size !== "inline" && size !== "circle" && (
        <footer className="wg-frame__foot">{observedLabel(observedAt)}</footer>
      )}
    </section>
  );
}
