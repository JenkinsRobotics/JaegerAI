/** The living avatar: the JaegerAvatar app's own stage (Vita by default), embedded while the app is running.
 *
 * `jaeger avatar` (or `python3 main.py` in the JaegerAvatar repository) starts the app at 127.0.0.1:8790;
 * this probes its /health and, once it answers, the panel shows the real rig — stream mode, so only the
 * character fills the frame. localStorage "jaeger.avatar.app.url" points elsewhere when the port differs.
 */
import { useEffect, useState } from "react";

const KEY = "jaeger.avatar.app.url";

export const avatarAppUrl = (): string => {
  try { return localStorage.getItem(KEY) ?? "http://127.0.0.1:8790"; } catch { return "http://127.0.0.1:8790"; }
};

const TEST = typeof import.meta !== "undefined" && (import.meta as { env?: { MODE?: string } }).env?.MODE === "test";

/** Whether the JaegerAvatar app answers; probed on mount and every pollMs. Inert under test. */
export function useAvatarApp(pollMs = 30000): boolean {
  const [up, setUp] = useState(false);
  useEffect(() => {
    if (TEST) return;
    let on = true;
    const probe = () => { try {
      fetch(`${avatarAppUrl()}/health`, { mode: "no-cors" }).then(() => { if (on) setUp(true); }, () => { if (on) setUp(false); });
    } catch { setUp(false); } };
    probe();
    const t = window.setInterval(probe, pollMs);
    return () => { on = false; window.clearInterval(t); };
  }, [pollMs]);
  return up;
}

export function LiveAvatarApp({ face = "vita", compact = false }: { face?: string; compact?: boolean }) {
  return (
    <iframe
      className="jg-av-live"
      data-compact={compact || undefined}
      title={`Live avatar (${face})`}
      src={`${avatarAppUrl()}/?face=${encodeURIComponent(face)}&stream`}
      allow="autoplay"
    />
  );
}
