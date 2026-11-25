import type { ApprovalPart } from "@jaeger/ui-protocol";

export interface ApprovalCardProps {
  approval: ApprovalPart;
  onDecision: (approvalId: string, decision: "approve" | "deny") => void;
  disabled?: boolean;
}

export function ApprovalCard({ approval, onDecision, disabled = false }: ApprovalCardProps) {
  const pending = approval.status === "pending";

  return (
    <div
      className="jg-approval-card"
      data-testid={`approval-card-${approval.approvalId}`}
      data-status={approval.status}
      style={{
        border: "1px solid var(--jg-border-strong)",
        borderRadius: "var(--jg-radius-md)",
        background: "var(--jg-surface-elevated)",
        padding: "12px",
        margin: "8px 0",
      }}
    >
      <div style={{ fontWeight: 600, fontSize: "13px", color: "var(--jg-text-primary)" }}>
        Approval required: {approval.toolName}
      </div>
      <p style={{ margin: "6px 0 10px", fontSize: "13px", color: "var(--jg-text-secondary)" }}>
        {approval.prompt}
      </p>
      {pending ? (
        <div style={{ display: "flex", gap: "8px" }}>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onDecision(approval.approvalId, "approve")}
            style={{
              padding: "6px 12px",
              borderRadius: "var(--jg-radius-sm)",
              border: "1px solid var(--jg-accent)",
              background: "var(--jg-accent)",
              color: "var(--jg-on-accent)",
              cursor: disabled ? "not-allowed" : "pointer",
              fontSize: "12.5px",
            }}
          >
            Approve
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onDecision(approval.approvalId, "deny")}
            style={{
              padding: "6px 12px",
              borderRadius: "var(--jg-radius-sm)",
              border: "1px solid var(--jg-border-subtle)",
              background: "transparent",
              color: "var(--jg-text-primary)",
              cursor: disabled ? "not-allowed" : "pointer",
              fontSize: "12.5px",
            }}
          >
            Deny
          </button>
        </div>
      ) : (
        <div style={{ fontSize: "12px", color: "var(--jg-text-secondary)" }}>
          Decision: {approval.status}
        </div>
      )}
    </div>
  );
}
