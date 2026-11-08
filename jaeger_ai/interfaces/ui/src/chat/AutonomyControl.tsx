import { useEffect, useRef, useState } from "react";
import type { RuntimeAutonomy } from "../api/source";
import { Check, Shield, ToolShield } from "../components/Icons";
import { useExclusivePopup } from "../popups/coordinator";
import type { ChatHost } from "./host";

type AutonomyHost = Pick<ChatHost, "runtimeAutonomy" | "setRuntimeAutonomy">;

const modes: Array<{ id: RuntimeAutonomy; label: string; description: string }> = [
  { id: "ask", label: "Ask for approval", description: "Ask before outward, hardware, and destructive actions." },
  { id: "scoped", label: "Approve for me", description: "Use saved scope and ask when a new risky action appears." },
  { id: "auto", label: "Full access", description: "Run permitted tools automatically. Hardline blocks still require you." },
];

const fallback = modes[0];
const details = (mode?: RuntimeAutonomy) => modes.find(item => item.id === mode) ?? fallback;

export function AutonomyControl({ host }: { host: AutonomyHost }) {
  const [current, setCurrent] = useState<RuntimeAutonomy>();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState<RuntimeAutonomy>();
  const [error, setError] = useState<string>();
  const trigger = useRef<HTMLButtonElement>(null);
  const available = Boolean(host.runtimeAutonomy && host.setRuntimeAutonomy);
  useExclusivePopup(open, () => setOpen(false), trigger.current);

  useEffect(() => {
    let live = true;
    if (!host.runtimeAutonomy) return;
    void host.runtimeAutonomy().then(
      snapshot => { if (live) { setCurrent(snapshot.autonomy); setError(undefined); } },
      () => { if (live) setError("Approval mode is unavailable."); },
    );
    return () => { live = false; };
  }, [host]);

  const select = async (mode: RuntimeAutonomy) => {
    if (!host.setRuntimeAutonomy || saving || mode === current) { if (mode === current) setOpen(false); return; }
    setSaving(mode);
    setError(undefined);
    try {
      const snapshot = await host.setRuntimeAutonomy(mode);
      if (snapshot.autonomy !== mode) throw new Error("Gateway returned a different approval mode");
      setCurrent(snapshot.autonomy);
      setOpen(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The approval mode did not change.");
    } finally {
      setSaving(undefined);
    }
  };

  const active = details(current);
  return (
    <div className="jg-autonomy">
      <button
        ref={trigger}
        type="button"
        className="jg-composer__policy"
        aria-label={`Approval mode: ${active.label}`}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={!available}
        title={available ? "Choose how Jaeger asks before using tools" : "Approval mode is unavailable"}
        onClick={() => { setError(undefined); setOpen(value => !value); }}
      >
        <ToolShield size={20} />
        <span className="jg-composer__policy-label">{active.label}</span>
      </button>
      {open && (
        <div className="jg-autonomy-menu" role="menu" aria-label="Tool approval mode">
          <header>How should Jaeger actions be approved?</header>
          {modes.map(mode => (
            <button
              key={mode.id}
              type="button"
              role="menuitemradio"
              aria-checked={current === mode.id}
              className={mode.id === "auto" ? "is-full-access" : undefined}
              disabled={Boolean(saving)}
              onClick={() => void select(mode.id)}
            >
              <Shield size={18} />
              <span><strong>{mode.label}</strong><small>{mode.description}</small></span>
              {saving === mode.id ? <span className="jg-autonomy-saving" aria-label="Saving" /> : current === mode.id ? <Check size={18} /> : null}
            </button>
          ))}
          {error && <p className="jg-autonomy-error" role="alert">{error}</p>}
        </div>
      )}
    </div>
  );
}
