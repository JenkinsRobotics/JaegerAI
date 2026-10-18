import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

const FOCUSABLE = 'button:not(:disabled), [href], [tabindex]:not([tabindex="-1"])';

export interface ProgressOverlayProps {
  open: boolean;
  label: ReactNode;
  detail?: ReactNode;
  phase?: ReactNode;
  value?: number;
  max?: number;
  onCancel?: () => void;
  onBackground?: () => void;
  inline?: boolean;
}

/** Progress surface for observable, cancellable, or backgroundable work. */
export function ProgressOverlay({
  open,
  label,
  detail,
  phase,
  value,
  max = 100,
  onCancel,
  onBackground,
  inline,
}: ProgressOverlayProps) {
  const cardRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!open || inline) return;
    const opener = document.activeElement as HTMLElement | null;
    const card = cardRef.current;
    card?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && onCancel) {
        event.preventDefault();
        event.stopPropagation();
        onCancel();
        return;
      }
      if (event.key !== "Tab" || !card) return;
      const focusables = Array.from(card.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const current = document.activeElement;
      if (event.shiftKey && (current === first || !card.contains(current))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (current === last || !card.contains(current))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      opener?.focus?.();
    };
  }, [inline, onCancel, open]);

  if (!open) return null;
  const determinate = value !== undefined;
  return (
    <div className={`aui-progress-surface${inline ? " aui-progress-surface--inline" : ""}`}>
      <section
        ref={cardRef}
        className="aui-progress-card"
        role={inline ? undefined : "dialog"}
        aria-modal={inline ? undefined : "true"}
        aria-label={!inline && typeof label === "string" ? label : undefined}
        aria-live="polite"
      >
        <div className="aui-progress-heading"><strong>{label}</strong>{phase ? <span>{phase}</span> : null}</div>
        {detail ? <p>{detail}</p> : null}
        <div
          className={`aui-progress-track${determinate ? "" : " aui-progress-track--indeterminate"}`}
          role="progressbar"
          aria-label={typeof label === "string" ? label : undefined}
          aria-valuemin={determinate ? 0 : undefined}
          aria-valuemax={determinate ? max : undefined}
          aria-valuenow={determinate ? value : undefined}
        >
          <span style={determinate ? { width: `${Math.min(100, Math.max(0, (value / max) * 100))}%` } : undefined} />
        </div>
        {onCancel || onBackground ? (
          <div className="aui-state-actions">
            {onBackground ? <button type="button" onClick={onBackground}>Run in background</button> : null}
            {onCancel ? <button type="button" onClick={onCancel}>Cancel</button> : null}
          </div>
        ) : null}
      </section>
    </div>
  );
}
