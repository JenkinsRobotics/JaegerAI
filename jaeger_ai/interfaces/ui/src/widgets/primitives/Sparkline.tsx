/**
 * Sparkline (Jenkins Robotics, 2026-10-29, original).
 *
 * The ONLY place a chart library may live. Widget definitions pass numbers and get
 * SVG back, so the rendering approach can be replaced without touching any widget.
 * Deliberately dependency-free: a polyline over a normalised viewBox.
 */
export interface SparklineProps {
  points: number[];
  /** Height in px. Width follows the container. */
  height?: number;
  /** Fill under the line. */
  area?: boolean;
  /** Accessible summary. Required: a chart with no text equivalent is not shipped. */
  label: string;
}

export function Sparkline({ points, height = 40, area = true, label }: SparklineProps) {
  if (points.length < 2) {
    return <div className="wg-spark wg-spark--empty" style={{ height }} aria-label={label} role="img" />;
  }
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const step = 100 / (points.length - 1);
  const path = points
    .map((value, index) => `${(index * step).toFixed(2)},${(100 - ((value - min) / span) * 100).toFixed(2)}`)
    .join(" ");
  const last = points[points.length - 1];

  return (
    <svg
      className="wg-spark"
      style={{ height }}
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      role="img"
      aria-label={`${label}: ${points.length} points, latest ${last}`}
    >
      {area && <polygon className="wg-spark__area" points={`0,100 ${path} 100,100`} />}
      <polyline className="wg-spark__line" points={path} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
