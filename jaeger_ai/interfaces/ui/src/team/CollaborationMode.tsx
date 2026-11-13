/* Collaboration mode — One mind / Team / Auto (Gateway /v1/runtime/collaboration).
 * One control, used in Settings → Agents and on the Team / Inner workings page.
 * The saved value lives in the instance config; the runtime reads it per message. */
import { useCallback, useEffect, useState } from "react";
import { Brain, Loader2, Users, Wand2 } from "lucide-react";
import type { CollaborationMode, CollaborationSnapshot, TeamApi } from "../api/team";
import "./team.css";

const ICON: Record<CollaborationMode, typeof Brain> = { one_mind: Brain, team: Users, auto: Wand2 };
const FALLBACK: CollaborationSnapshot["options"] = [
  { id: "one_mind", label: "One mind", description: "Every message goes to Jaeger. Specialists work as inner helpers and Jaeger answers in one voice." },
  { id: "team", label: "Team", description: "Team rooms, @Name hand-offs and a roster you can chat with." },
  { id: "auto", label: "Auto", description: "Jaeger decides per task: inner helpers by default, team rooms only when you open a room or @mention an agent." },
];

export function useCollaborationMode(api?: TeamApi) {
  const [snap, setSnap] = useState<CollaborationSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    if (!api?.mode) return;
    try { setSnap(await api.mode()); setError(null); } catch (e) { setError((e as Error).message); }
  }, [api]);
  useEffect(() => { void load(); }, [load]);
  const choose = useCallback(async (mode: CollaborationMode) => {
    if (!api?.setMode) return null;
    setBusy(true);
    try { const next = await api.setMode(mode); setSnap(next); setError(null); return next; }
    catch (e) { setError((e as Error).message); return null; }
    finally { setBusy(false); }
  }, [api]);
  return { snap, busy, error, choose, reload: load, available: !!api?.mode };
}

export function CollaborationModeControl({ api, compact, onChanged }: { api?: TeamApi; compact?: boolean; onChanged?: (mode: CollaborationMode) => void }) {
  const { snap, busy, error, choose, available } = useCollaborationMode(api);
  if (!available) return null;
  const options = snap?.options?.length ? snap.options : FALLBACK;
  const current = snap?.mode;
  return (
    <div className={`jg-collab${compact ? " is-compact" : ""}`}>
      {!compact && <div className="jg-collab__label" id="jg-collab-label">Collaboration mode</div>}
      <div className="jg-collab__seg" role="radiogroup" aria-labelledby={compact ? undefined : "jg-collab-label"} aria-label={compact ? "Collaboration mode" : undefined}>
        {options.map((o) => {
          const Icon = ICON[o.id] ?? Brain;
          return (
            <button key={o.id} type="button" role="radio" aria-checked={current === o.id} title={o.description}
              className={`jg-collab__opt${current === o.id ? " is-on" : ""}`} disabled={busy || !snap}
              onClick={() => { if (current !== o.id) void choose(o.id).then((n) => { if (n) onChanged?.(n.mode); }); }}>
              <Icon size={13} /> {o.label}
            </button>);
        })}
        {busy && <Loader2 size={13} className="jg-team-spin" aria-label="Saving" />}
      </div>
      {!compact && <p className="jg-collab__hint">{options.find((o) => o.id === current)?.description ?? "Loading…"}</p>}
      {error && <p className="jg-collab__error" role="alert">{error}</p>}
    </div>
  );
}

export default CollaborationModeControl;
