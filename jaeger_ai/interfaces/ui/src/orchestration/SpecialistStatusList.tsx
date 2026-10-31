import { AgentAvatar } from "../agents/AgentAvatar";
import { label } from "../agents/agentsLogic";
import { statusTone } from "./feed";
import type { AgentLive } from "./types";

export function runnerText(runner?: string) {
  if (!runner) return undefined;
  return runner.startsWith("delegate:") ? `via ${runner.slice(9)}` : runner === "native" ? "native" : runner;
}

/** Specialists with live status, current task and runner. */
export function SpecialistStatusList({ team, selected, onSelect }: { team: AgentLive[]; selected?: string; onSelect: (agentId: string | undefined) => void }) {
  return (
    <ul className="jg-orch-team" aria-label="Specialists">
      {team.map((t) => (
        <li key={t.agent.id}>
          <button type="button" className="jg-orch-member" aria-pressed={selected === t.agent.id} onClick={() => onSelect(selected === t.agent.id ? undefined : t.agent.id)}>
            <AgentAvatar id={t.agent.id} name={label(t.agent)} src={t.agent.avatar_url} size={28} />
            <span className="jg-orch-member-text">
              <span className="jg-orch-member-name">{label(t.agent)}</span>
              <span className="jg-orch-member-sub">{t.currentTask?.goal ?? (t.status === "idle" ? "Idle" : t.status.replace(/_/g, " "))}</span>
            </span>
            <span className="jg-orch-member-meta">
              <span className="jg-orch-dot" data-tone={statusTone(t.status)} aria-label={t.status.replace(/_/g, " ")} />
              {t.currentTask?.eta != null && <span>{String(t.currentTask.eta)}</span>}
              {runnerText(t.runner) && <span className="jg-orch-runner">{runnerText(t.runner)}</span>}
              {t.offRoster && <span className="jg-orch-runner" title="Hidden or archived in the roster; shown because it worked on handoffs or tasks">hidden</span>}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
