/**
 * Custom (AI-generated) widget (Jenkins Robotics, 2026-10-30, original).
 *
 * One definition, kind "custom.ai", renders ANY spec produced by
 * POST /v1/widgets/generate. The spec is declarative data persisted in the
 * layout item's `params` — this file never evals it, and the backend already
 * validated it against a closed schema. `load()` reads the real source named
 * in the spec and resolves only the metric keys the spec references; every
 * number shown comes from the gateway, never from the model.
 */
import { registerWidget } from "../registry";
import { SkeletonStat } from "../primitives/Skeleton";
import { Sparkline } from "../primitives/Sparkline";
import type { JaegerSource, GatewayDiagnostics } from "../../api/source";
import type { WidgetDef } from "../types";

/** The validated spec shape (mirrors jaeger_ai/core/gateway/widget_routes.py). */
export interface AiWidgetSpec {
  v: 1;
  source: "diagnostics" | "sessions" | "agents" | "tasks" | "approvals";
  title: string;
  about: string;
  metrics: { key: string; label: string }[];
  chart: "none" | "stat" | "bar" | "sparkline" | "list";
  size: "sm" | "md" | "lg";
  hosts: string[];
}

interface MetricValue {
  label: string;
  value: number | null; // null = the source does not report this key right now
}

interface CustomData {
  spec: AiWidgetSpec;
  metrics: MetricValue[];
  listCount?: number; // for chart "list": row count of the underlying source
  observedLabel: string;
}

function isSpec(value: unknown): value is AiWidgetSpec {
  if (!value || typeof value !== "object") return false;
  const s = value as Partial<AiWidgetSpec>;
  return (
    s.v === 1 &&
    typeof s.source === "string" &&
    typeof s.title === "string" &&
    Array.isArray(s.metrics) &&
    typeof s.chart === "string"
  );
}

/** Resolve one dotted metric key against a diagnostics snapshot. */
function readDiagnosticsMetric(d: GatewayDiagnostics, key: string): number | null {
  if (key === "sessions") return d.sessions;
  if (key === "unknown_requests") return d.unknown_requests?.length ?? null;
  if (key === "process_id") return d.process_id ?? null;
  const dot = key.indexOf(".");
  if (dot > 0) {
    const head = key.slice(0, dot);
    const tail = key.slice(dot + 1);
    const bag =
      head === "requests" ? d.requests :
      head === "approvals" ? d.approvals :
      head === "handoffs" ? d.handoffs : undefined;
    if (bag && tail in bag) return Number(bag[tail]) || 0;
  }
  return null;
}

async function loadData(source: JaegerSource, spec: AiWidgetSpec): Promise<CustomData> {
  // Only sources the UI can genuinely read are supported; the backend schema
  // allows more, so anything else is an honest error rather than invented data.
  if (spec.source !== "diagnostics") {
    throw new Error(`This build can only render "${spec.source}" widgets from live sources it supports (diagnostics).`);
  }
  if (!source.diagnostics) throw new Error("This gateway does not expose diagnostics.");
  const d = await source.diagnostics();
  const metrics = spec.metrics.map((m) => ({
    label: m.label,
    value: readDiagnosticsMetric(d, m.key),
  }));
  const observedLabel = new Date(d.observed_at * 1000).toLocaleTimeString();
  return { spec, metrics, observedLabel };
}

export const customAiWidget: WidgetDef<{ spec: AiWidgetSpec }, CustomData> = {
  kind: "custom.ai",
  title: "Custom",
  about: "A widget you asked Jaeger to design",
  sizes: ["sm", "md", "lg"],
  hosts: ["page", "float", "overlay"],
  skeleton: <SkeletonStat />,
  async load(source, params) {
    if (!isSpec(params?.spec)) {
      throw new Error("No widget spec was stored with this widget. Remove it and ask again.");
    }
    return loadData(source, params.spec);
  },
  view({ data, size }) {
    const { spec, metrics, observedLabel } = data;
    const title = spec?.title ?? "Custom";
    const compact = size === "sm";
    const known = metrics.filter((m) => m.value !== null);
    const unknown = metrics.length - known.length;

    if (spec.chart === "stat" && known.length >= 1) {
      const m = known[0];
      return (
        <div className="wg-health wg-health--compact">
          <span className="wg-health__value">{m.value}</span>
          <span className="wg-health__label">{m.label}</span>
        </div>
      );
    }

    if (spec.chart === "bar" && known.length > 1) {
      const max = Math.max(...known.map((m) => m.value ?? 0), 1);
      return (
        <div className="wg-custom">
          <ul className="wg-custom__bars">
            {known.map((m) => (
              <li key={m.label} className="wg-custom__bar-row">
                <span className="wg-custom__bar-label">{m.label}</span>
                <span className="wg-custom__bar-track">
                  <span
                    className="wg-custom__bar-fill"
                    style={{ width: `${Math.round(((m.value ?? 0) / max) * 100)}%` }}
                  />
                </span>
                <span className="wg-custom__bar-value">{m.value}</span>
              </li>
            ))}
          </ul>
          <p className="wg-health__prov">source: gateway diagnostics · {observedLabel}</p>
        </div>
      );
    }

    if (spec.chart === "sparkline" && known.length > 1) {
      return (
        <div className="wg-custom">
          <Sparkline
            points={known.map((m) => m.value ?? 0)}
            label={title}
            height={compact ? 28 : 44}
          />
          <p className="wg-health__prov">source: gateway diagnostics · {observedLabel}</p>
        </div>
      );
    }

    // "list" / "none" / compact fallthrough: labelled stats.
    return (
      <div className="wg-health">
        <div className="wg-health__stats">
          {known.slice(0, compact ? 1 : 4).map((m) => (
            <div className="wg-health__stat" key={m.label}>
              <span className="wg-health__value">{m.value}</span>
              <span className="wg-health__label">{m.label}</span>
            </div>
          ))}
        </div>
        {unknown > 0 && (
          <p className="wg-health__note">
            {unknown} metric{unknown === 1 ? "" : "s"} not reported by this gateway
          </p>
        )}
        <p className="wg-health__prov">source: gateway diagnostics · {observedLabel}</p>
      </div>
    );
  },
};

registerWidget(customAiWidget);

/** Sizes an AI spec wants, expressed as grid units on the page host. */
export function specToUnit(spec: AiWidgetSpec): { w: number; h: number } {
  switch (spec.size) {
    case "sm": return { w: 3, h: 3 };
    case "lg": return { w: 6, h: 6 };
    default: return { w: 4, h: 4 };
  }
}

/** Stable layout key for a generated spec (title + metric keys), so re-adding the same ask is idempotent. */
export function specKey(spec: AiWidgetSpec): string {
  const sig = spec.metrics.map((m) => m.key).join("+");
  return `custom.ai:${spec.source}:${sig}`;
}
