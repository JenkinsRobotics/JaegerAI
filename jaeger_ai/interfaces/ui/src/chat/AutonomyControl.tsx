import { useEffect, useRef, useState } from "react";
import type { RuntimeAutonomy } from "../api/source";
import { AlertCircle, Check, ChevronDown, Shield, ToolShield, Zap } from "../components/Icons";
import { useExclusivePopup } from "../popups/coordinator";
import type { ChatHost } from "./host";

type AutonomyHost = Pick<ChatHost, "runtimeAutonomy" | "setRuntimeAutonomy">;

const modes: Array<{ id: RuntimeAutonomy; label: string; description: string; icon: typeof Shield }> = [
  { id: "ask", label: "Ask for approval", description: "Ask before outward, hardware, and destructive actions.", icon: Shield },
  { id: "scoped", label: "Approve for me", description: "Actions inside saved scope run automatically. Actions outside scope are reviewed by a model; if it is unsure or would deny, you will be asked.", icon: ToolShield },
  { id: "auto", label: "Full access", description: "Run permitted tools automatically. Hardline blocks still require you.", icon: Zap },
];

const fallback = modes[0];
const details = (mode?: RuntimeAutonomy) => modes.find(item => item.id === mode) ?? fallback;

export function AutonomyControl({ host, dimmed = false }: { host: AutonomyHost; dimmed?: boolean }) {
  const [current, setCurrent] = useState<RuntimeAutonomy>();
  const [reading, setReading] = useState(false);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState<RuntimeAutonomy>();
  const [error, setError] = useState<string>();
  const trigger = useRef<HTMLButtonElement>(null);
  const refreshGeneration = useRef(0);
  const available = Boolean(host.runtimeAutonomy && host.setRuntimeAutonomy);
  useExclusivePopup(open, () => setOpen(false), trigger.current);

  useEffect(() => {
    let live = true;
    setCurrent(undefined);
    if (!host.runtimeAutonomy) return;
    void host.runtimeAutonomy().then(
      snapshot => { if (live) { setCurrent(snapshot.autonomy); setError(undefined); } },
      () => { if (live) setError("Approval mode is unavailable."); },
    );
    return () => { live = false; };
  }, [host]);

  const select = async (mode: RuntimeAutonomy) => {
    if (!host.setRuntimeAutonomy || saving || mode === current) { if (mode === current) setOpen(false); return; }
    refreshGeneration.current += 1;
    setReading(false);
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

  const refresh = async () => {
    if (!host.runtimeAutonomy) return;
    const generation = ++refreshGeneration.current;
    setReading(true);
    try { const snapshot = await host.runtimeAutonomy(); if (generation === refreshGeneration.current) { setCurrent(snapshot.autonomy); setError(undefined); } }
    catch { if (generation === refreshGeneration.current) { setCurrent(undefined); setError("Cannot verify approval mode. Retry before changing permissions."); } }
    finally { if (generation === refreshGeneration.current) setReading(false); }
  };
  const active = current ? details(current) : {label: "Approval mode unavailable"};
  return (
    <div className={`jg-autonomy${dimmed ? " is-dimmed" : ""}`}>
      <button
        ref={trigger}
        type="button"
        className="jg-composer__policy jg-autonomy__trigger"
        aria-label={`Permissions: ${active.label}`}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={!available || dimmed}
        title={dimmed ? "Approvals apply when tools are available in Agent or Plan mode" : available ? "Choose how Jaeger asks before using tools" : "Approval mode is unavailable"}
        onClick={() => { if (dimmed) return; setOpen(value => !value); if (!open) void refresh(); }}
      >
        <ToolShield size={20} />
        <span className="jg-composer__policy-label">{active.label}</span>
        <ChevronDown size={14} className="jg-composer__chevron" />
      </button>
      {open && (
        <div className="jg-autonomy-menu" role="menu" aria-label="Tool approval mode">
          <header>How should Jaeger actions be approved?</header><p className="jg-autonomy-scope">Applies to this Jaeger instance across conversations and devices. System safety restrictions still apply.</p>
          {modes.map(mode => (
            <button
              key={mode.id}
              type="button"
              role="menuitemradio"
              aria-checked={current === mode.id}
              className={mode.id === "auto" ? "is-full-access" : undefined}
              disabled={Boolean(saving) || !current}
              onClick={() => void select(mode.id)}
            >
              <mode.icon size={18} />
              <span><strong>{mode.label}</strong><small>{mode.description}</small></span>
              {saving === mode.id ? <span className="jg-autonomy-saving" aria-label="Saving" /> : current === mode.id ? <Check size={18} /> : null}
            </button>
          ))}
          {error && <p className="jg-autonomy-error" role="alert">{error} <button type="button" disabled={reading} onClick={() => void refresh()}>Retry</button></p>}
          <footer className="jg-autonomy-menu__footer">
            <button type="button" className="jg-autonomy-menu__learn" onClick={() => setOpen(false)}>
              <AlertCircle size={14} /> Learn more about permissions
            </button>
          </footer>
        </div>
      )}
    </div>
  );
}
