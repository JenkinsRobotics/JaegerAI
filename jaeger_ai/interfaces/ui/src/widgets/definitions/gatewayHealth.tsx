/**
 * Gateway health widget (Jenkins Robotics, 2026-10-29, original).
 *
 * Every value comes from `source.diagnostics()` → GatewayDiagnostics. No derived
 * numbers, no percentages of invented totals. Fields shown are exactly the fields
 * the gateway reports; anything the gateway does not report is not displayed.
 */
import { registerWidget } from "../registry";
import { SkeletonStat } from "../primitives/Skeleton";
import { Sparkline } from "../primitives/Sparkline";
import type { GatewayDiagnostics } from "../../api/source";
import type { WidgetDef } from "../types";

interface Health {
  /** The raw gateway snapshot. Kept whole so the view can show provenance. */
  diagnostics: GatewayDiagnostics;
  /** Request counts summed from `diagnostics.requests`, grouped by outcome verb. */
  requestTotals: { key: string; count: number }[];
  pendingApprovals: number;
}

export const gatewayHealthWidget: WidgetDef<void, Health> = {
  kind: "gateway.health",
  title: "Gateway",
  about: "See gateway sessions, request outcomes and pending approvals",
  sizes: ["sm", "md", "lg"],
  hosts: ["page", "float", "overlay"],
  skeleton: <SkeletonStat />,
  async load(source) {
    if (!source.diagnostics) {
      throw new Error("This gateway does not expose diagnostics.");
    }
    const diagnostics = await source.diagnostics();
    const requestTotals = Object.entries(diagnostics.requests ?? {})
      .map(([key, count]) => ({ key, count: Number(count) || 0 }))
      .sort((a, b) => b.count - a.count);
    const pendingApprovals = Object.values(diagnostics.approvals ?? {}).reduce<number>(
      (sum, value) => sum + (Number(value) || 0),
      0,
    );
    return { diagnostics, requestTotals, pendingApprovals };
  },
  view({ data, size, tint }) {
    const { diagnostics, requestTotals, pendingApprovals } = data;
    const compact = size === "sm" || tint === "tinted";
    const ok = requestTotals.find((r) => /ok|success/i.test(r.key))?.count ?? 0;
    const failed = requestTotals.find((r) => /fail|error/i.test(r.key))?.count ?? 0;

    if (compact) {
      return (
        <div className="wg-health wg-health--compact">
          <span className="wg-health__value">{diagnostics.sessions}</span>
          <span className="wg-health__label">sessions</span>
          {pendingApprovals > 0 && (
            <span className="wg-health__badge">{pendingApprovals} to approve</span>
          )}
        </div>
      );
    }

    return (
      <div className="wg-health">
        <div className="wg-health__stats">
          <div className="wg-health__stat">
            <span className="wg-health__value">{diagnostics.sessions}</span>
            <span className="wg-health__label">sessions</span>
          </div>
          <div className="wg-health__stat">
            <span className="wg-health__value">{ok}</span>
            <span className="wg-health__label">requests ok</span>
          </div>
          <div className="wg-health__stat">
            <span className="wg-health__value wg-health__value--warn">{failed}</span>
            <span className="wg-health__label">failed</span>
          </div>
          <div className="wg-health__stat">
            <span className="wg-health__value">{pendingApprovals}</span>
            <span className="wg-health__label">approvals</span>
          </div>
        </div>

        {size === "lg" && requestTotals.length > 1 && (
          <Sparkline
            points={requestTotals.map((r) => r.count)}
            label="Request counts by outcome"
            height={44}
          />
        )}

        {size === "lg" && diagnostics.unknown_requests.length > 0 && (
          <p className="wg-health__note">
            {diagnostics.unknown_requests.length} request
            {diagnostics.unknown_requests.length === 1 ? "" : "s"} with unknown outcome
          </p>
        )}

        <p className="wg-health__prov">
          pid {diagnostics.process_id} · read-only snapshot
        </p>
      </div>
    );
  },
};

registerWidget(gatewayHealthWidget);
