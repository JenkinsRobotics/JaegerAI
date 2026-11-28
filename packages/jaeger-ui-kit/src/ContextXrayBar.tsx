/**
 * Context & 32 GB Unified-Memory X-Ray Meter (adapted from Goose context_xray, Apache-2.0).
 */

export interface ContextXrayBarProps {
  usedTokens: number;
  maxTokens: number;
  hostTotalGb?: number;
  hostAvailableGb?: number;
  activeModel?: string;
}

export function ContextXrayBar({
  usedTokens,
  maxTokens,
  hostTotalGb,
  hostAvailableGb,
  activeModel,
}: ContextXrayBarProps) {
  const ctxPct = Math.min(100, Math.round((usedTokens / Math.max(1, maxTokens)) * 100));
  const ramUsedGb =
    hostTotalGb !== undefined && hostAvailableGb !== undefined
      ? Math.max(0, hostTotalGb - hostAvailableGb)
      : undefined;
  const ramPct =
    ramUsedGb !== undefined && hostTotalGb
      ? Math.min(100, Math.round((ramUsedGb / hostTotalGb) * 100))
      : undefined;

  return (
    <div className="jg-xray-bar" role="status" aria-label="Context and 32GB resource meter">
      <div className="jg-xray-item">
        <span className="jg-xray-label">Context</span>
        <div className="jg-meter">
          <div className={`jg-meter-fill ${ctxPct > 80 ? "is-warn" : ""}`} style={{ width: `${ctxPct}%` }} />
        </div>
        <span className="jg-xray-val">{ctxPct}%</span>
      </div>
      {ramPct !== undefined && hostTotalGb !== undefined && hostAvailableGb !== undefined && (
        <div className="jg-xray-item">
          <span className="jg-xray-label">Memory</span>
          <div className="jg-meter">
            <div className={`jg-meter-fill ${ramPct > 85 ? "is-warn" : ""}`} style={{ width: `${ramPct}%` }} />
          </div>
          <span className="jg-xray-val">
            {hostAvailableGb.toFixed(1)}/{hostTotalGb.toFixed(0)} GB free
          </span>
        </div>
      )}
      {activeModel && <span className="jg-pill jg-xray-model">{activeModel}</span>}
    </div>
  );
}
