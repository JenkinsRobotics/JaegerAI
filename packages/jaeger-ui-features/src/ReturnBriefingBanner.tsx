import { useCallback, useEffect, useRef, useState } from "react";

interface BriefingPayload {
  ok?: boolean;
  summary?: string;
  pending_approvals_count?: number;
  recent_actions?: Array<{ action_id?: string; kind?: string; summary?: string }>;
  active_goals?: Array<{ goal_id?: string; title?: string; domain?: string }>;
}

export interface ReturnBriefingBannerProps {
  baseUrl: string;
  onOpenOffice?: () => void;
  onOpenApprovals?: () => void;
}

export function ReturnBriefingBanner({
  baseUrl,
  onOpenOffice,
  onOpenApprovals,
}: ReturnBriefingBannerProps) {
  const [briefing, setBriefing] = useState<BriefingPayload | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const hiddenAtRef = useRef<number>(0);

  const loadBriefing = useCallback(async () => {
    try {
      const r = await fetch(`${baseUrl}/v1/cognition/briefing`);
      if (!r.ok) return;
      const d = (await r.json()) as BriefingPayload;
      if (d.ok) setBriefing(d);
    } catch {
      // Non-fatal
    }
  }, [baseUrl]);

  useEffect(() => {
    void loadBriefing();
    const onVis = () => {
      if (document.hidden) {
        hiddenAtRef.current = Date.now();
      } else if (hiddenAtRef.current > 0 && Date.now() - hiddenAtRef.current > 120_000) {
        setDismissed(false);
        void loadBriefing();
      }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [loadBriefing]);

  if (dismissed || !briefing) return null;
  const actionsCount = briefing.recent_actions?.length ?? 0;
  const approvalsCount = briefing.pending_approvals_count ?? 0;
  if (actionsCount === 0 && approvalsCount === 0) return null;

  const latestAction = briefing.recent_actions?.[0];

  return (
    <div
      className="jg-card"
      role="region"
      aria-label="While you were away briefing"
      style={{
        margin: "8px 16px 0",
        padding: "10px 14px",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        gap: 12,
        flexWrap: "wrap",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 3, minWidth: 220, flex: 1 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <strong style={{ fontSize: 13 }}>While you were away</strong>
          {approvalsCount > 0 && (
            <span className="jg-pill">{approvalsCount} approval(s) waiting</span>
          )}
          {actionsCount > 0 && (
            <span className="jg-pill">{actionsCount} self-action(s)</span>
          )}
        </div>
        <div className="jg-muted" style={{ fontSize: 12.5 }}>
          {latestAction
            ? `[${latestAction.kind ?? "auto"}] ${latestAction.summary ?? ""}`
            : briefing.summary?.split("\n")[0]}
        </div>
      </div>

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {approvalsCount > 0 && onOpenApprovals && (
          <button type="button" className="jg-btn jg-btn-primary" onClick={onOpenApprovals}>
            Review Approvals
          </button>
        )}
        {onOpenOffice && (
          <button type="button" className="jg-btn" onClick={onOpenOffice}>
            Open Office
          </button>
        )}
        <button type="button" className="jg-btn-ghost" onClick={() => setDismissed(true)}>
          Dismiss
        </button>
      </div>
    </div>
  );
}
