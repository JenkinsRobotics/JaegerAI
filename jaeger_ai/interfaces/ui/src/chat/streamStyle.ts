/* Stream style (shared setting with IDE Chat). LOCAL MIRROR of the canonical type that will live in
 * jaeger-chat packages/jaeger-chat-ui/src/streamStyle.ts (StreamStyleId, StreamStyleParams, STREAM_STYLES,
 * resolveStreamStyle); keep the names identical so swapping to the package import is a small diff.
 * The "grok" preset is measured from Grok Bot 0.71.2 (spec: jaeger-shots/specs/stream-grok.md); the
 * others are PROVISIONAL placeholders until measured. */
import { useSyncExternalStore } from "react";

export type StreamStyleId = "vscode" | "grok" | "chatgpt" | "claude" | "instant";

export interface StreamStyleParams {
  id: StreamStyleId;
  reveal: {
    mode: "raw" | "chars" | "words" | "tokens";
    /** Units per second (the floor when `adaptive`). */
    ratePerSec: number;
    tickMs: number;
    /** When the backlog exceeds this many characters, catch up. */
    maxLagChars: number;
    catchUp: "snap" | "accelerate";
    /** Estimate the incoming rate and pace to it; ratePerSec becomes the floor. */
    adaptive?: boolean;
  };
  enter: { kind: "none" | "fade" | "fadeSlide"; durationMs: number; easing: string; translatePx?: number };
  markdown: { midStream: "live" | "deferBlocks"; partialFence: "plain" | "highlightOnClose" | "live" };
  indicator: { kind: "none" | "caret" | "dots" | "shimmerLine" | "avatar" };
  scroll: { follow: "always" | "whenAtBottom"; thresholdPx: number; smooth: boolean };
}

export const STREAM_STYLES: Record<StreamStyleId, StreamStyleParams> = {
  // Measured: Grok's word reveal (50 ms stagger per word = 20 words/s, words via Intl.Segmenter, earlier words
  // settle at once = snap), 200 ms ease-out fade-in (Grok adds blur 4px→0), markdown re-parsed live on every
  // delta with the open fence already a code block, avatar progress line, follow only while pinned within 4 px,
  // smooth for deltas up to one viewport. See stream-grok.md for each source.
  grok: {
    id: "grok",
    reveal: { mode: "words", ratePerSec: 20, tickMs: 50, maxLagChars: 600, catchUp: "snap", adaptive: true },
    enter: { kind: "fade", durationMs: 200, easing: "ease-out" },
    markdown: { midStream: "live", partialFence: "live" },
    indicator: { kind: "avatar" },
    scroll: { follow: "whenAtBottom", thresholdPx: 4, smooth: true },
  },
  // PROVISIONAL placeholders (not measured yet).
  vscode: {
    id: "vscode",
    reveal: { mode: "words", ratePerSec: 40, tickMs: 50, maxLagChars: 1200, catchUp: "accelerate", adaptive: true },
    enter: { kind: "none", durationMs: 0, easing: "linear" },
    markdown: { midStream: "live", partialFence: "highlightOnClose" },
    indicator: { kind: "dots" },
    scroll: { follow: "whenAtBottom", thresholdPx: 40, smooth: false },
  },
  chatgpt: {
    id: "chatgpt",
    reveal: { mode: "chars", ratePerSec: 180, tickMs: 16, maxLagChars: 800, catchUp: "accelerate", adaptive: true },
    enter: { kind: "fade", durationMs: 150, easing: "ease-out" },
    markdown: { midStream: "live", partialFence: "live" },
    indicator: { kind: "caret" },
    scroll: { follow: "whenAtBottom", thresholdPx: 60, smooth: true },
  },
  claude: {
    id: "claude",
    reveal: { mode: "words", ratePerSec: 30, tickMs: 33, maxLagChars: 900, catchUp: "accelerate", adaptive: true },
    enter: { kind: "fadeSlide", durationMs: 240, easing: "cubic-bezier(.2,.8,.2,1)", translatePx: 4 },
    markdown: { midStream: "deferBlocks", partialFence: "highlightOnClose" },
    indicator: { kind: "shimmerLine" },
    scroll: { follow: "whenAtBottom", thresholdPx: 80, smooth: true },
  },
  instant: {
    id: "instant",
    reveal: { mode: "raw", ratePerSec: 0, tickMs: 0, maxLagChars: 0, catchUp: "snap" },
    enter: { kind: "none", durationMs: 0, easing: "linear" },
    markdown: { midStream: "live", partialFence: "highlightOnClose" },
    indicator: { kind: "dots" },
    scroll: { follow: "whenAtBottom", thresholdPx: 80, smooth: false },
  },
};

export const STREAM_STYLE_IDS = Object.keys(STREAM_STYLES) as StreamStyleId[];
export const STREAM_STYLE_LABELS: Record<StreamStyleId, string> = {
  grok: "Grok", vscode: "VS Code (provisional)", chatgpt: "ChatGPT (provisional)", claude: "Claude (provisional)", instant: "Instant (no smoothing)",
};
/** The Mac app's default. */
export const DEFAULT_STREAM_STYLE: StreamStyleId = "grok";

export function resolveStreamStyle(id?: string | null): StreamStyleParams {
  return STREAM_STYLES[(id ?? "") as StreamStyleId] ?? STREAM_STYLES[DEFAULT_STREAM_STYLE];
}

// Persisted choice (Settings → Chat → Stream style), shared by every open chat.
export const STREAM_STYLE_KEY = "jaeger.ui.stream-style";
const listeners = new Set<() => void>();
function read(): StreamStyleId {
  try { return resolveStreamStyle(localStorage.getItem(STREAM_STYLE_KEY)).id; } catch { return DEFAULT_STREAM_STYLE; }
}
export function setStreamStyle(id: StreamStyleId) {
  try { localStorage.setItem(STREAM_STYLE_KEY, id); } catch { /* private mode: session only */ }
  listeners.forEach((l) => l());
}
export function useStreamStyle(): StreamStyleParams {
  const id = useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, read, read);
  return STREAM_STYLES[id];
}
