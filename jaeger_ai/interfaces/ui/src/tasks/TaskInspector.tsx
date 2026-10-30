import { useState } from 'react';
import type { Task, Agent } from '../api/types';
import type { JaegerSource } from '../api/source';
import { label, runnerLabel } from '../agents/agentsLogic';
import { TaskArtifacts } from '../library/TaskArtifacts';
import { TaskPresentationControls } from './TaskPresentationControls';
import {
  Clock,
  AlertCircle,
  FileText,
  X,
} from '../components/Icons';

export interface TaskInspectorProps {
  task: Task;
  agents: Agent[];
  source: JaegerSource;
  busy?: boolean;
  onClose: () => void;
  onApprove?: (task: Task) => void;
  onEdit?: (task: Task) => void;
  onCancel?: (taskId: string) => void;
  onPresentationChange?: () => void;
}

export function TaskInspector({
  task,
  agents,
  source,
  busy,
  onClose,
  onApprove,
  onEdit,
  onCancel,
  onPresentationChange,
}: TaskInspectorProps) {
  const [activeTab, setActiveTab] = useState<'overview' | 'steps' | 'artifacts'>('overview');

  const agent = agents.find((a) => a.id === (task.agent_id ?? task.owning_agent));
  const agentDisplayName = agent ? label(agent) : task.agent_id ?? task.owning_agent ?? 'Unassigned';
  const state = String(task.state ?? 'queued');

  const isTerminal = ['done', 'completed', 'completed_verified', 'needs_owner', 'blocked', 'failed', 'cancelled'].includes(state);
  const isProposal = state === 'paused' && task.provenance?.authorized === false && !task.run_history?.length;

  const history = Array.isArray(task.run_history) ? task.run_history : [];

  return (
    <div className="jg-task-inspector" aria-label={`Task inspector: ${task.task_id}`}>
      <div className="jg-task-inspector__header">
        <div className="jg-task-inspector__title-area">
          <div className="jg-task-inspector__chips">
            <span className={`jg-task-widget__dot jg-task-widget__dot--${state}`} />
            <span className="jg-task-widget__state-badge">{state.replace(/_/g, ' ')}</span>
            <span className="jg-task-inspector__agent">{agentDisplayName}</span>
            {runnerLabel(task.runner) && (
              <span className="jg-tag jg-tag--runner">{runnerLabel(task.runner)}</span>
            )}
          </div>
          <h2 className="jg-task-inspector__goal">{task.goal ?? task.task_id}</h2>
        </div>
        <button
          type="button"
          className="jg-task-inspector__close-btn"
          onClick={onClose}
          aria-label="Close inspector"
        >
          <X size={16} />
        </button>
      </div>

      <div className="jg-task-inspector__toolbar">
        {source.taskActions && (
          <div className="jg-task-inspector__actions">
            {isProposal && typeof task.updated_at === 'number' && (
              <>
                {onEdit && (
                  <button
                    type="button"
                    className="jg-btn jg-btn--secondary"
                    disabled={busy}
                    onClick={() => onEdit(task)}
                  >
                    Edit proposal
                  </button>
                )}
                {onApprove && (
                  <button
                    type="button"
                    className="jg-btn jg-btn--primary"
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
                className="jg-btn jg-btn--danger"
                disabled={busy}
                onClick={() => onCancel(task.task_id)}
              >
                Cancel task
              </button>
            )}
          </div>
        )}

        {source.taskPresentation && task.presentation && typeof task.updated_at === 'number' && (
          <TaskPresentationControls
            task={task}
            controls={source.taskPresentation}
            changed={onPresentationChange ?? (() => {})}
          />
        )}
      </div>

      <div className="jg-task-inspector__tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'overview'}
          className={`jg-task-inspector__tab ${activeTab === 'overview' ? 'jg-task-inspector__tab--active' : ''}`}
          onClick={() => setActiveTab('overview')}
        >
          Overview & Context
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'steps'}
          className={`jg-task-inspector__tab ${activeTab === 'steps' ? 'jg-task-inspector__tab--active' : ''}`}
          onClick={() => setActiveTab('steps')}
        >
          Execution Steps {history.length > 0 && `(${history.length})`}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'artifacts'}
          className={`jg-task-inspector__tab ${activeTab === 'artifacts' ? 'jg-task-inspector__tab--active' : ''}`}
          onClick={() => setActiveTab('artifacts')}
        >
          Artifacts & Deliverables
        </button>
      </div>

      <div className="jg-task-inspector__body">
        {activeTab === 'overview' && (
          <div className="jg-task-inspector__overview">
            {task.error && (
              <div className="jg-task-inspector__error-box" role="alert">
                <AlertCircle size={16} />
                <div>
                  <strong>Task execution issue:</strong>
                  <p>{task.error}</p>
                </div>
              </div>
            )}

            <div className="jg-task-inspector__meta-grid">
              <div className="jg-task-inspector__meta-item">
                <span className="jg-task-inspector__meta-label">Task ID</span>
                <span className="jg-task-inspector__meta-value">{task.task_id}</span>
              </div>
              <div className="jg-task-inspector__meta-item">
                <span className="jg-task-inspector__meta-label">Assigned Bot</span>
                <span className="jg-task-inspector__meta-value">{agentDisplayName}</span>
              </div>
              <div className="jg-task-inspector__meta-item">
                <span className="jg-task-inspector__meta-label">State</span>
                <span className="jg-task-inspector__meta-value">{state}</span>
              </div>
              {task.eta && (
                <div className="jg-task-inspector__meta-item">
                  <span className="jg-task-inspector__meta-label">Estimated Completion</span>
                  <span className="jg-task-inspector__meta-value">{task.eta}</span>
                </div>
              )}
              <div className="jg-task-inspector__meta-item">
                <span className="jg-task-inspector__meta-label">Origin Session</span>
                <span className="jg-task-inspector__meta-value">
                  {task.provenance?.session_id ?? 'None recorded'}
                </span>
              </div>
              <div className="jg-task-inspector__meta-item">
                <span className="jg-task-inspector__meta-label">Origin Request</span>
                <span className="jg-task-inspector__meta-value">
                  {task.provenance?.request_id ?? 'None recorded'}
                </span>
              </div>
              <div className="jg-task-inspector__meta-item">
                <span className="jg-task-inspector__meta-label">Last Revision</span>
                <span className="jg-task-inspector__meta-value">
                  {task.updated_at ? new Date(task.updated_at * 1000).toLocaleString() : 'Unknown'}
                </span>
              </div>
            </div>

            {task.result != null && (
              <div className="jg-task-inspector__result-section">
                <h3>Execution Result</h3>
                <pre className="jg-task-inspector__code-block">
                  {typeof task.result === 'string' ? task.result : JSON.stringify(task.result, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}

        {activeTab === 'steps' && (
          <div className="jg-task-inspector__steps">
            {history.length === 0 ? (
              <div className="jg-task-inspector__empty-tab">
                <Clock size={24} />
                <p>No execution steps recorded yet.</p>
                <span className="jg-muted">Activity will appear in real time as the agent runs.</span>
              </div>
            ) : (
              <div className="jg-task-inspector__timeline">
                {history.map((step, idx) => {
                  const stepObj = (typeof step === 'object' && step !== null) ? (step as Record<string, unknown>) : null;
                  const stepTitle = stepObj?.action ?? stepObj?.step ?? stepObj?.name ?? `Step ${idx + 1}`;
                  const stepDetail = stepObj ? JSON.stringify(stepObj, null, 2) : String(step);

                  return (
                    <div key={idx} className="jg-task-inspector__timeline-step">
                      <div className="jg-task-inspector__step-node">
                        <span className="jg-task-inspector__step-number">{idx + 1}</span>
                      </div>
                      <div className="jg-task-inspector__step-card">
                        <div className="jg-task-inspector__step-header">
                          <strong>{String(stepTitle)}</strong>
                        </div>
                        <pre className="jg-task-inspector__step-detail">{stepDetail}</pre>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {activeTab === 'artifacts' && (
          <div className="jg-task-inspector__artifacts">
            {source.taskArtifacts ? (
              <TaskArtifacts controls={source.taskArtifacts} taskId={task.task_id} />
            ) : (
              <div className="jg-task-inspector__empty-tab">
                <FileText size={24} />
                <p>Artifact management is not available from this gateway.</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
