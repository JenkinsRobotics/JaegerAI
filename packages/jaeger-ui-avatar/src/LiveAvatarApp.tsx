/**
 * Living Avatar stage embed (ported cleanly from origin/jaeger-avatar).
 *
 * Probes the optional sibling JaegerAvatar app (default http://127.0.0.1:8791,
 * overridable via localStorage["jaeger.avatar.app.url"]). Inert under Vitest.
 */
import { useEffect, useState } from "react";

const STORAGE_KEY = "jaeger.avatar.app.url";
const DEFAULT_URL = "http://127.0.0.1:8791";

export const avatarAppUrl = (): string => {
  try {
    return (localStorage.getItem(STORAGE_KEY) || DEFAULT_URL).replace(/\/+$/, "");
  } catch {
    return DEFAULT_URL;
  }
};

const IS_TEST =
  typeof import.meta !== "undefined" &&
  Boolean((import.meta as { env?: { MODE?: string } }).env?.MODE === "test");

export function useAvatarApp(pollMs = 30000): boolean {
  const [up, setUp] = useState(false);
  useEffect(() => {
    if (IS_TEST) return;
    let active = true;
    const probe = () => {
      try {
        fetch(`${avatarAppUrl()}/health`, { mode: "no-cors" }).then(
          () => {
            if (active) setUp(true);
          },
          () => {
            if (active) setUp(false);
          },
        );
      } catch {
        if (active) setUp(false);
      }
    };
    probe();
    const timer = window.setInterval(probe, pollMs);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [pollMs]);
  return up;
}

export interface LiveAvatarAppProps {
  face?: string;
  compact?: boolean;
}

export function LiveAvatarApp({
  face = "vita",
  compact = false,
}: LiveAvatarAppProps) {
  return (
    <iframe
      className="jg-av-live"
      data-compact={compact || undefined}
      title={`Live avatar (${face})`}
      src={`${avatarAppUrl()}/?face=${encodeURIComponent(face)}&stream`}
      allow="autoplay"
      style={{
        display: "block",
        width: "100%",
        aspectRatio: compact ? "1 / 1" : "3 / 4",
        minHeight: compact ? 180 : 320,
        border: 0,
        borderRadius: 12,
        background: "#000",
      }}
    />
  );
}
