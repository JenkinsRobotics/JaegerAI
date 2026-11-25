import { useEffect, useId, useRef, useState } from "react";
import { ChevronUp, X } from "lucide-react";
import type { JaegerSource, NotificationPreferences } from "../api/source";
import { Badge } from "../unified/ui";
import { getJson, type SystemStatus } from "../unified/webui";

type Props = {
  source: JaegerSource;
  ready: boolean;
  error?: string;
  host?: string;
  compact?: boolean;
  onNavigate: (path: string) => void;
};

export function SystemStatusButton({ source, ready, error, host, compact, onNavigate }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const labelId = useId();
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<SystemStatus>();
  const [failed, setFailed] = useState(false);
  const [prefs, setPrefs] = useState<NotificationPreferences>();
  const [preferenceUnavailable, setPreferenceUnavailable] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const connection = error ? "Connection error" : ready ? "Connected" : "Connecting…";
  const light = error ? "error" : ready ? "ready" : "pending";

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const read = () => void getJson<SystemStatus>("/v1/system/status", controller.signal).then(value => {
      if (!controller.signal.aborted) { setStatus(value); setFailed(false); }
    }, () => {
      if (!controller.signal.aborted) { setStatus(undefined); setFailed(true); }
    });
    read();
    const timer = setInterval(read, 30000);
    void source.notifications?.read().then(value => {
      if (!controller.signal.aborted) { setPrefs(value.preferences); setPreferenceUnavailable(false); }
    }, () => {
      if (!controller.signal.aborted) { setPrefs(undefined); setPreferenceUnavailable(true); }
    });
    return () => { controller.abort(); clearInterval(timer); };
  }, [open, source]);

  const toggleFocus = async () => {
    if (!source.notifications || !prefs || saving) return;
    setSaving(true); setNotice("");
    try {
      const result = await source.notifications.save({
        expected_revision: prefs.revision, enabled: !prefs.enabled, muted_agent_ids: prefs.muted_agent_ids,
      });
      setPrefs(result.preferences);
    } catch { setNotice("Couldn’t change Focus. Reopen System status to refresh the setting."); }
    finally { setSaving(false); }
  };

  return <>
    <button type="button" className={compact ? "jg-ushell__rail-btn jg-status-trigger--compact" : "jg-status-trigger"}
      aria-haspopup="dialog" aria-expanded={open} aria-controls={labelId + "-dialog"} aria-label={`System status: ${connection}`}
      title={compact ? `System status · ${connection}` : undefined}
      onClick={event => {
        const panel = dialog.current;
        if (!panel || panel.open) return;
        const rect = event.currentTarget.getBoundingClientRect();
        panel.style.setProperty("--jg-status-left", `${Math.max(12, rect.left)}px`);
        panel.style.setProperty("--jg-status-bottom", `${Math.max(12, innerHeight - rect.top + 8)}px`);
        setStatus(undefined); setFailed(false); setNotice(""); setPrefs(undefined); setPreferenceUnavailable(false);
        panel.showModal(); setOpen(true);
      }}>
      <span className="jg-status-light" data-state={light} aria-hidden="true" />
      {!compact && <><span>{connection}</span><ChevronUp size={14} aria-hidden="true" /></>}
    </button>
    <dialog id={labelId + "-dialog"} ref={dialog} className="jg-status-popup" aria-labelledby={labelId}
      onClose={() => setOpen(false)} onClick={event => { if (event.target === event.currentTarget) event.currentTarget.close(); }}>
      {open && <div className="jg-status-popup__body">
        <header><h2 id={labelId}>System status</h2><button type="button" className="jg-ushell__icon-btn" aria-label="Close system status" onClick={() => dialog.current?.close()}><X size={16} /></button></header>
        <dl className="jg-status-popup__rows">
          <div><dt>Connection{host && <small>{host}</small>}</dt><dd><Badge tone={error ? "bad" : ready ? "ok" : "warn"}>{connection}</Badge></dd></div>
          <div><dt>Gateway</dt><dd>{status?.gateway ? status.gateway.ok ? `Healthy${status.gateway.latency_ms == null ? "" : ` · ${status.gateway.latency_ms} ms`}` : "Unreachable" : failed ? "Not available" : "Checking…"}</dd></div>
          <div><dt>Tailscale</dt><dd>{status?.tailscale ? !status.tailscale.available ? "Not available" : status.tailscale.online ? "Online" : "Offline" : failed ? "Not available" : "Checking…"}</dd></div>
          {source.notifications && <div><dt>Focus<small>{prefs && !prefs.enabled ? "Notifications paused" : "Notification preference"}</small></dt>
            <dd>{prefs ? <button type="button" className="jg-u-btn" aria-label="Focus" aria-pressed={!prefs.enabled} disabled={saving} onClick={() => void toggleFocus()}>{prefs.enabled ? "Off" : "On"}</button> : preferenceUnavailable ? "Not available" : "Checking…"}</dd></div>}
        </dl>
        {notice && <p role="alert" className="jg-u-note">{notice}</p>}
        <button type="button" className="jg-u-btn" onClick={() => { dialog.current?.close(); onNavigate("/settings/machine"); }}>Machine settings</button>
      </div>}
    </dialog>
  </>;
}
