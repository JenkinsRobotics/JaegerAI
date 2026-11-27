import { useState } from "react";
import type { ThinkingPart } from "@jaeger/ui-protocol";

export interface ThinkingDisclosureProps {
  part: ThinkingPart;
  defaultOpen?: boolean;
  autoOpen?: boolean;
}

export function ThinkingDisclosure({ part, defaultOpen = false, autoOpen = false }: ThinkingDisclosureProps) {
  const [manualOpen, setManualOpen] = useState<boolean>();
  const open = manualOpen ?? (defaultOpen || autoOpen);
  const label = part.streaming
    ? "Thinking…"
    : typeof part.durationMs === "number"
      ? `Thought for ${(part.durationMs / 1000).toFixed(1)}s`
      : "Reasoning";

  return (
    <div
      className="jg-thinking-disclosure"
      data-testid="thinking-disclosure"
      style={{
        borderLeft: "2px solid var(--jg-border-subtle)",
        paddingLeft: "10px",
        margin: "6px 0",
        color: "var(--jg-text-secondary)",
        fontSize: "12.5px",
      }}
    >
      <button
        type="button"
        onClick={() => setManualOpen(!open)}
        aria-expanded={open}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "6px",
          background: "transparent",
          border: "none",
          padding: "2px 0",
          color: "var(--jg-text-secondary)",
          cursor: "pointer",
          fontSize: "12px",
        }}
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
          <path
            d={open ? "M2.5 4.5 6 8l3.5-3.5" : "M4.5 2.5 8 6l-3.5 3.5"}
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <span>{label}</span>
      </button>
      {open && (
        <div
          style={{
            marginTop: "4px",
            whiteSpace: "pre-wrap",
            lineHeight: 1.45,
            maxHeight: "320px",
            overflowY: "auto",
          }}
        >
          {part.text}
        </div>
      )}
    </div>
  );
}
