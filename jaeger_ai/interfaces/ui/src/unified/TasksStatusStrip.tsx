/**
 * Tasks header status strip: the useful tiles from the retired Home dashboard, folded into the one
 * Tasks view. Live data only: gateway health (/v1/system/status), read-only Tailscale, Focus (the
 * gateway notification preference), the research-job runner (/v1/jobs/runner, pause/resume) and
 * pending approvals. Host CPU/memory/disk graphs live on the Machine page.
 */
import { useCallback, useEffect, useState } from "react";
import type { JaegerSource, NotificationPreferences } from "../api/source";
import { approvalsLabel, useApprovalSessions } from "./ApprovalTray";
import { useToast, type Tone } from "./ui";
import { getJson, sendJson, type SystemStatus } from "./webui";
import { summarizeRunner, type RunnerStatus } from "./jobsRunner";
import { Globe, Moon, Sparkles, Zap } from "../components/Icons";
import { WidgetCard } from "../widgets/primitives/WidgetCard";

function usePoll<T>(path: string, ms: number) {
  const [v, setV] = useState<T>();
  const [err, setErr] = useState<string>();
  const read = useCallback(() => {
    getJson<T>(path).then((x) => { setV(x); setErr(undefined); }, (e: unknown) => setErr(String((e as Error).message ?? e)));
  }, [path]);
  useEffect(() => { read(); const t = setInterval(read, ms); return () => clearInterval(t); }, [read, ms]);
  return { v, err, read };
}

function Tile({ icon, title, value, tone, on, onClick, hint }: { icon: React.ReactNode; title: string; value: string; tone?: Tone; on?: boolean; onClick?: () => void; hint?: string }) {
  return <div className="jg-cc__tile" data-pressed={on || undefined} title={hint}>
    <WidgetCard title={title} status={<span role={onClick ? undefined : "status"}>{value}</span>} actions={onClick &&
      <button type="button" className="jg-cc__action" aria-label={`${title} ${value}`} aria-pressed={on} onClick={onClick} title={hint}>
        <span className="jg-cc__icon" data-tone={tone}>{icon}</span>
      </button>}>
      {!onClick && <span className="jg-cc__icon" data-tone={tone}>{icon}</span>}
    </WidgetCard>
  </div>;
}

export function TasksStatusStrip({ source, onNavigate, onNeedsYou }: { source: JaegerSource; onNavigate: (to: string) => void; onNeedsYou: () => void }) {
  const toast = useToast();
  const status = usePoll<SystemStatus>("/v1/system/status", 30000);
  const runner = usePoll<RunnerStatus>("/v1/jobs/runner", 10000);
  const rs = summarizeRunner(runner.v, runner.err);
  const approvals = useApprovalSessions(source);
  const pending = approvals.reduce((n, a) => n + a.count, 0);
  const [prefs, setPrefs] = useState<NotificationPreferences>();
  useEffect(() => {
    let live = true;
    source.notifications?.read().then((n) => { if (live) setPrefs(n.preferences); }, () => {});
    return () => { live = false; };
  }, [source]);
  const gw = status.v?.gateway;
  const ts = status.v?.tailscale;
  const focusOn = prefs ? !prefs.enabled : false;

  const toggleFocus = async () => {
    if (!source.notifications || !prefs) return;
    try {
      const r = await source.notifications.save({ expected_revision: prefs.revision, enabled: !prefs.enabled, muted_agent_ids: prefs.muted_agent_ids });
      setPrefs(r.preferences);
      toast(r.preferences.enabled ? "Focus off: notifications on" : "Focus on: notifications paused");
    } catch (e) { toast(`Couldn't change Focus: ${(e as Error).message}`, "error"); }
  };
  const toggleJob = async () => {
    const job = rs.job;
    if (!job) return;
    try {
      await sendJson("POST", `/v1/research/youtube/${encodeURIComponent(job.task_id)}/${job.paused ? "resume" : "pause"}`, {});
      toast(job.paused ? "Research job resumed" : "Research job paused: running steps finish, no new ones start");
      runner.read();
    } catch (e) { toast(`Couldn't change the job: ${(e as Error).message}`, "error"); }
  };

  return (
    <section className="jg-cc jg-tasks__status" aria-label="Status">
      <Tile icon={<Zap size={18} />} title="Gateway" value={gw ? (gw.ok ? `Healthy · ${gw.latency_ms} ms` : "Unreachable") : status.err ? "Unknown" : "Checking…"} tone={gw ? (gw.ok ? "ok" : "bad") : undefined} hint="Read-only: GET /health · graphs on the Machine page" onClick={() => onNavigate("/machine")} />
      <Tile icon={<Globe size={18} />} title="Tailscale" value={!ts ? "Checking…" : !ts.available ? "Not available" : `${ts.online ? "Online" : ts.state ?? "Offline"} · ${ts.peers_online ?? 0}/${ts.peers ?? 0} peers`} tone={ts?.available ? (ts.online ? "ok" : "warn") : undefined} hint={ts?.host ? `This Mac: ${ts.host} (read-only)` : "Read-only"} />
      <Tile icon={<Moon size={18} />} title="Focus" value={!source.notifications ? "Unavailable" : !prefs ? "…" : focusOn ? "On · notifications paused" : "Off"} on={focusOn} onClick={source.notifications && prefs ? () => void toggleFocus() : undefined} />
      <Tile icon={<Sparkles size={18} />} title="Research jobs" value={rs.value} tone={rs.tone} hint={rs.hint} on={rs.job?.paused} onClick={rs.job ? () => void toggleJob() : undefined} />
      <Tile icon={<Sparkles size={18} />} title="Approvals" value={approvalsLabel(pending)} tone={pending ? "warn" : "ok"} onClick={pending ? () => onNavigate("/chat") : onNeedsYou} hint={pending ? "Approvals wait in their chats" : "Show tasks that need you"} />
    </section>
  );
}
