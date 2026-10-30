import type { Task, Agent } from '../api/types';
import { label, runnerLabel } from '../agents/agentsLogic';
import { Check, Clock, AlertCircle, ChevronRight } from '../components/Icons';

export interface TaskWidgetProps {
  task: Task;
  agents: Agent[];
  selected?: boolean;
  busy?: boolean;
  onSelect: (taskId: string) => void;
  onCancel?: (taskId: string) => void;
  onApprove?: (task: Task) => void;
  onEdit?: (task: Task) => void;
}

const terminalStates = ['done', 'completed', 'completed_verified', 'needs_owner', 'blocked', 'failed', 'cancelled'];
export const isTaskTerminal = (task: Task) => terminalStates.includes(String(task.state));
export const isTaskProposal = (task: Task) =>
  task.state === 'paused' && task.provenance?.authorized === false && !task.run_history?.length;

export function computeTaskProgress(task: Task): { percent: number; label: string; isIndeterminate: boolean } {
  const state = String(task.state ?? '');

  if (['done', 'completed', 'completed_verified'].includes(state)) {
    return { percent: 100, label: 'Completed', isIndeterminate: false };
  }
  if (['failed', 'cancelled'].includes(state)) {
    return { percent: 100, label: state === 'failed' ? 'Failed' : 'Cancelled', isIndeterminate: false };
  }
  if (['needs_owner', 'blocked', 'paused'].includes(state)) {
    const historyCount = task.run_history?.length ?? 0;
    const basePercent = Math.min(85, Math.max(15, historyCount * 20));
    return { percent: basePercent, label: 'Awaiting operator input', isIndeterminate: false };
  }
  if (state === 'running') {
    const historyCount = task.run_history?.length ?? 0;
    if (historyCount > 0) {
      const stepPercent = Math.min(90, 20 + historyCount * 15);
      return { percent: stepPercent, label: `Step ${historyCount} in progress`, isIndeterminate: false };
    }
    return { percent: 45, label: 'Running…', isIndeterminate: true };
  }
  if (state === 'queued') {
    return { percent: 5, label: 'Queued', isIndeterminate: false };
  }

  return { percent: 0, label: state || 'Pending', isIndeterminate: false };
}

export function TaskWidget({
  task,
  agents,
  selected,
  busy,
  onSelect,
  onCancel,
  onApprove,
  onEdit,
}: TaskWidgetProps) {
  const agent = agents.find((a) => a.id === (task.agent_id ?? task.owning_agent));
  const agentDisplayName = agent ? label(agent) : task.agent_id ?? task.owning_agent ?? 'Unassigned';
  const progress = computeTaskProgress(task);
  const state = String(task.state ?? 'queued');

  const isTerminal = isTaskTerminal(task);
  const isProposal = isTaskProposal(task);
  const needsAttention = ['needs_owner', 'blocked', 'paused'].includes(state);

  return (
    <article
      role="button"
      tabIndex={0}
      className={`jg-task-widget jg-task-widget--${state} ${selected ? 'jg-task-widget--selected' : ''}`}
      onClick={() => onSelect(task.task_id)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect(task.task_id);
        }
      }}
      aria-label={`Task: ${task.goal ?? task.task_id}`}
      aria-selected={selected}
    >
      <div className="jg-task-widget__header">
        <div className="jg-task-widget__status-strip">
          <span className={`jg-task-widget__dot jg-task-widget__dot--${state}`} />
          <span className="jg-task-widget__state-badge">{state.replace(/_/g, ' ')}</span>
          {needsAttention && <span className="jg-task-widget__attention-badge">Needs You</span>}
        </div>
        <div className="jg-task-widget__meta-chips">
          {runnerLabel(task.runner) && (
            <span className="jg-tag jg-tag--runner">{runnerLabel(task.runner)}</span>
          )}
          <span className="jg-task-widget__agent">{agentDisplayName}</span>
        </div>
      </div>

      <div className="jg-task-widget__goal" title={task.goal ?? task.task_id}>
        {task.goal ?? task.task_id}
      </div>

      <div className="jg-task-widget__progress-section">
        <div className="jg-task-widget__progress-bar">
          <div
            className={`jg-task-widget__progress-fill jg-task-widget__progress-fill--${state} ${
              progress.isIndeterminate ? 'jg-task-widget__progress-fill--indeterminate' : ''
            }`}
            style={{ width: `${progress.percent}%` }}
          />
        </div>
        <div className="jg-task-widget__progress-info">
          <span className="jg-task-widget__progress-text">{progress.label}</span>
          {task.eta && (
            <span className="jg-task-widget__eta">
              <Clock size={11} /> ETA {task.eta}
            </span>
          )}
        </div>
      </div>

      {task.error && (
        <div className="jg-task-widget__error" role="alert">
          <AlertCircle size={13} />
          <span>{task.error}</span>
        </div>
      )}

      <div className="jg-task-widget__footer">
        <div className="jg-task-widget__footer-left">
          <span className="jg-task-widget__id">#{task.task_id.slice(0, 8)}</span>
          {task.result != null && (
            <span className="jg-task-widget__result-chip" title="Artifact or result available">
              <Check size={11} /> Result
            </span>
          )}
        </div>

        <div className="jg-task-widget__actions" onClick={(e) => e.stopPropagation()}>
          {isProposal && typeof task.updated_at === 'number' && (
            <>
              {onEdit && (
                <button
                  type="button"
                  className="jg-btn-mini"
                  disabled={busy}
                  onClick={() => onEdit(task)}
                >
                  Edit proposal
                </button>
              )}
              {onApprove && (
                <button
                  type="button"
                  className="jg-btn-mini jg-btn-mini--primary"
                  disabled={busy}
                  onClick={() => onApprove(task)}
                >
                  Approve this version
                </button>
              )}
            </>
          )}
          {!isTerminal && onCancel && (
            <button
              type="button"
              className="jg-btn-mini jg-btn-mini--danger"
              disabled={busy}
              onClick={() => onCancel(task.task_id)}
            >
              Cancel task
            </button>
          )}
          <ChevronRight size={14} className="jg-task-widget__chevron" />
        </div>
      </div>
    </article>
  );
}
