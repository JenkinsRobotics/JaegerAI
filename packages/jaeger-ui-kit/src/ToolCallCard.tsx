import { useState } from "react";
import type { ToolCallPart } from "@jaeger/ui-protocol";

export interface ToolCallCardProps {
  part: ToolCallPart;
  defaultOpen?: boolean;
  autoOpen?: boolean;
}

export function ToolCallCard({ part, defaultOpen = false, autoOpen = false }: ToolCallCardProps) {
  const [manualOpen, setManualOpen] = useState<boolean>();
  const open = manualOpen ?? (defaultOpen || autoOpen);

  return (
    <div
      className="jg-tool-card"
      data-testid={`tool-card-${part.callId}`}
      data-status={part.status}
      style={{
        border: "1px solid var(--jg-border-subtle)",
        borderRadius: "var(--jg-radius-md)",
        background: "var(--jg-surface-elevated)",
        margin: "6px 0",
        overflow: "hidden",
      }}
    >
      <button
        type="button"
        onClick={() => setManualOpen(!open)}
        aria-expanded={open}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "8px",
          padding: "8px 12px",
          background: "transparent",
          border: "none",
          color: "var(--jg-text-primary)",
          cursor: "pointer",
          fontSize: "13px",
          textAlign: "left",
        }}
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}>
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path
              d="M10.5 2.5a3 3 0 0 0-3.7 3.7L2.5 10.5a1.4 1.4 0 1 0 2 2l4.3-4.3a3 3 0 0 0 3.7-3.7L11 6l-1-1 1.5-1.5Z"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <strong>{part.toolName}</strong>
        </span>
        <span
          style={{
            fontSize: "11px",
            color:
              part.status === "failed"
                ? "var(--jg-status-danger)"
                : part.status === "completed"
                  ? "var(--jg-status-success)"
                  : "var(--jg-text-secondary)",
          }}
        >
          {part.status}
          {typeof part.durationMs === "number" ? ` · ${part.durationMs}ms` : ""}
        </span>
      </button>
      {open && (
        <div
          style={{
            borderTop: "1px solid var(--jg-border-subtle)",
            padding: "8px 12px",
            fontSize: "12px",
            color: "var(--jg-text-secondary)",
          }}
        >
          {part.args && (
            <pre style={{ margin: "0 0 6px", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {JSON.stringify(part.args, null, 2)}
            </pre>
          )}
          {part.error ? (
            <div style={{ color: "var(--jg-status-danger)" }}>{part.error}</div>
          ) : part.output !== undefined ? (
            <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {typeof part.output === "string" ? part.output : JSON.stringify(part.output, null, 2)}
            </pre>
          ) : null}
        </div>
      )}
    </div>
  );
}
