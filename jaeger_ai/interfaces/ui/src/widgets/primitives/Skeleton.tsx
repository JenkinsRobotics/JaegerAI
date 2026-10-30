/**
 * Skeleton (Jenkins Robotics, 2026-10-29, original).
 *
 * Shown while a widget's loader is in flight. Renders neutral bars only — never
 * numbers, never "0", never a previous value. A skeleton that shows data is a lie
 * about freshness.
 */
import type { CSSProperties } from "react";

export function Skeleton({
  lines = 3,
  width,
  height = 10,
}: {
  lines?: number;
  width?: CSSProperties["width"];
  height?: number;
}) {
  return (
    <div className="wg-skeleton" aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <span
          key={i}
          className="wg-skeleton__bar"
          style={{ height, width: i === lines - 1 ? "60%" : (width ?? "100%") }}
        />
      ))}
    </div>
  );
}

/** A skeleton sized like a stat widget: one big block and a label bar. */
export function SkeletonStat() {
  return (
    <div className="wg-skeleton wg-skeleton--stat" aria-hidden="true">
      <span className="wg-skeleton__bar" style={{ height: 28, width: "45%" }} />
      <span className="wg-skeleton__bar" style={{ height: 10, width: "65%" }} />
    </div>
  );
}
