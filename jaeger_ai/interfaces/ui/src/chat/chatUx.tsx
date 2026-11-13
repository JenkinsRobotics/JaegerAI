import { useEffect, useState, type ReactNode } from "react";
import { Copy, RefreshCw, ThumbsDown, ThumbsUp, Workflow } from "../components/Icons";
import { navigate } from "../shell/router";

export function thinkingSeconds(startedAt?: number | string, now = Date.now()): number {
  const start = typeof startedAt === "string" ? Date.parse(startedAt) : startedAt;
  if (!start || !Number.isFinite(start)) return 0;
  return Math.max(0, Math.floor((now - start) / 1000));
}

export function relativeTime(value?: string | number, now = Date.now()): string {
  if (value == null || value === "") return "";
  const start = typeof value === "number" ? (value < 1e12 ? value * 1000 : value) : Date.parse(value);
  if (!Number.isFinite(start)) return "";
  const seconds = Math.round((now - start) / 1000);
  if (seconds < 45) return "just now";
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))}m ago`;
  if (seconds < 86400) return `${Math.max(1, Math.round(seconds / 3600))}h ago`;
  return new Date(start).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function isDebugThinking(text?: string): boolean {
  return Boolean(text && /^\s*\[adapter\b/i.test(text));
}

export function modelErrorTitle(): string {
  return "Couldn't reach the model";
}

export function ThinkingRow({ startedAt, durationMs, text, live, sessionId }: {
  startedAt?: number | string; durationMs?: number; text?: string; live: boolean; sessionId?: string;
}): ReactNode {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!live) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [live]);
  const seconds = durationMs !== undefined ? Math.max(0, Math.round(durationMs / 1000)) : thinkingSeconds(startedAt, now);
  const label = live ? `Thinking… ${seconds}s` : `Thought for ${seconds}s`;
  const shown = text && !isDebugThinking(text) ? text : undefined;
  const href = sessionId ? `/work/process?session=${encodeURIComponent(sessionId)}` : undefined;
  return (
    <details className={`jg-thinking${live ? " jg-thinking--live" : ""}`} open={live && shown ? true : undefined}>
      <summary>
        <span className="jg-thinking__shimmer">{label}</span>
        {href && (
          <a className="jg-thinking__process" href={href} title="Open Process view" aria-label="Open Process view"
            onClick={(event) => { event.preventDefault(); event.stopPropagation(); navigate(href); }}>
            <Workflow size={16} />
          </a>
        )}
      </summary>
      {shown ? <p>{shown}</p> : null}
    </details>
  );
}

export function ModelError({ details, onRetry }: { details: string[]; onRetry?: () => void }): ReactNode {
  const unique = [...new Set(details.map((item) => item.trim()).filter(Boolean))];
  return (
    <div className="jg-error" role="alert">
      <div className="jg-error__row">
        <p className="jg-error__message">{modelErrorTitle()}</p>
        {onRetry && <button type="button" className="jg-error__retry" onClick={onRetry}>Retry</button>}
      </div>
      {unique.length > 0 && (
        <details>
          <summary>Details</summary>
          <pre>{unique.join("\n")}</pre>
        </details>
      )}
    </div>
  );
}

export function MessageActions({ createdAt, copied, onCopy, onRetry, up, down, onThumb }: {
  createdAt?: string | number; copied?: boolean; onCopy: () => void; onRetry?: () => void;
  up?: boolean; down?: boolean; onThumb?: (emoji: string, active: boolean) => void;
}): ReactNode {
  const touch = typeof window !== "undefined" && window.matchMedia("(hover: none)").matches;
  return (
    <div className={`jg-msg-actions${touch ? " is-touch" : ""}`}>
      <button type="button" aria-label={copied ? "Copied" : "Copy"} onClick={onCopy}><Copy size={15} /></button>
      {onRetry && <button type="button" aria-label="Retry" onClick={onRetry}><RefreshCw size={15} /></button>}
      {onThumb && (
        <>
          <button type="button" aria-label="Good response" aria-pressed={up} onClick={() => onThumb("👍", !up)}><ThumbsUp size={15} /></button>
          <button type="button" aria-label="Bad response" aria-pressed={down} onClick={() => onThumb("👎", !down)}><ThumbsDown size={15} /></button>
        </>
      )}
      {createdAt && <span className="jg-msg-actions__time">{relativeTime(createdAt)}</span>}
    </div>
  );
}
