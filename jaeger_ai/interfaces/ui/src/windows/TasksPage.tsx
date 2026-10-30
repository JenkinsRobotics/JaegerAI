/**
 * TasksPage — Mission Gallery (Jenkins Robotics, 2026-10-30).
 *
 * The Agents tab format applied to tasks: the same header with stat-filter
 * buttons, the same search field, the same card grid (`bots-page.css` classes),
 * and the same detail modal — with task state instead of character category.
 * Every row is one task from the live gateway (`source.tasks()`); the modal
 * shows the task's own goal, provenance, error and execution result only.
 */
import { useEffect, useMemo, useState } from 'react'
import {
  Search,
  Zap,
  X,
} from '../components/Icons'
import type { JaegerSource } from '../api/source'
import type { Task } from '../api/types'
import './bots-page.css'

// Same family values as the character gallery: all / needs-you / working / done.
type TaskFilter = 'all' | 'needs' | 'working' | 'done'

/**
 * TEMPLATE WORKSHOP LIMIT (temporary): while the page template is being
 * designed, show only one task card so the resting layout is visible and the
 * natural 1→2→3-across expansion of the auto-fill grid can be checked.
 * Real counts stay in the stat buttons. Remove this cap (set to Infinity)
 * once the template is agreed — real data was never deleted.
 */
const TEMPLATE_LIMIT = 1

const NEEDS_YOU = new Set(['needs_owner', 'paused', 'blocked'])
const WORKING = new Set(['queued', 'running'])
const DONE = new Set(['done', 'completed', 'completed_verified', 'failed', 'cancelled'])

function stateLabel(state?: string): string {
  return (state ?? 'unknown').replace(/_/g, ' ')
}

/** Relative time from an epoch-seconds stamp: the "2m ago" glance signal. */
function timeAgo(ts?: number | null): string {
  if (!ts) return ''
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts))
  if (s < 60) return 'just now'
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

/**
 * First line of the objective as the card title: task goals here are whole
 * paragraphs; the card shows the leading sentence, the modal shows everything.
 * A leading bracket tag like "[skill-review:plan]" is metadata — returned
 * separately so it can render as a chip instead of bloating the title.
 */
function splitGoalTag(goal?: string): { tag: string | null; body: string } {
  const text = (goal ?? '').trim()
  const m = text.match(/^\[([^\]]{1,60})\]\s*/)
  if (m) return { tag: m[1], body: text.slice(m[0].length).trim() }
  return { tag: null, body: text }
}

function goalTitle(goal?: string, fallback?: string): string {
  const { body } = splitGoalTag(goal)
  const firstLine = body.split('\n')[0] ?? ''
  if (!firstLine) return fallback ?? 'Untitled task'
  const m = firstLine.match(/^(.{1,90}?[.!?])(\s|$)/)
  return m ? m[1] : firstLine.length > 90 ? firstLine.slice(0, 87).trimEnd() + '…' : firstLine
}

function stateDotClass(state?: string): string {
  switch (state) {
    case 'running': return 'task-card__dot--running'
    case 'queued': return 'task-card__dot--queued'
    case 'needs_owner': case 'paused': case 'blocked': return 'task-card__dot--needs'
    case 'failed': return 'task-card__dot--failed'
    case 'done': case 'completed': case 'completed_verified': return 'task-card__dot--done'
    default: return 'task-card__dot--other'
  }
}

export interface TasksPageProps {
  source?: JaegerSource
}

export function TasksPage({ source }: TasksPageProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [filter, setFilter] = useState<TaskFilter>('all')
  const [selectedTask, setSelectedTask] = useState<Task | null>(null)
  const [tasks, setTasks] = useState<Task[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    if (!source?.tasks) {
      setError('This gateway does not expose a task list.')
      return
    }
    source
      .tasks()
      .then((rows) => {
        if (!live) return
        setTasks(rows)
        setError(null)
      })
      .catch((e) => live && setError(String((e as Error).message ?? e)))
    return () => {
      live = false
    }
  }, [source])

  const filteredTasks = useMemo(() => {
    let result = tasks ?? []
    if (filter === 'needs') result = result.filter((t) => NEEDS_YOU.has(String(t.state)))
    if (filter === 'working') result = result.filter((t) => WORKING.has(String(t.state)))
    if (filter === 'done') result = result.filter((t) => DONE.has(String(t.state)))
    if (searchQuery) {
      const q = searchQuery.toLowerCase()
      result = result.filter(
        (t) =>
          (t.goal ?? '').toLowerCase().includes(q) ||
          t.task_id.toLowerCase().includes(q) ||
          (t.owning_agent ?? '').toLowerCase().includes(q),
      )
    }
    // Pinned first, then most recently updated.
    const sorted = [...result].sort(
      (a, b) =>
        Number(Boolean(b.presentation?.pinned)) - Number(Boolean(a.presentation?.pinned)) ||
        (b.updated_at ?? 0) - (a.updated_at ?? 0),
    )
    return TEMPLATE_LIMIT === Infinity ? sorted : sorted.slice(0, TEMPLATE_LIMIT)
  }, [tasks, filter, searchQuery])

  const stats = useMemo(
    () => ({
      total: (tasks ?? []).length,
      needs: (tasks ?? []).filter((t) => NEEDS_YOU.has(String(t.state))).length,
      working: (tasks ?? []).filter((t) => WORKING.has(String(t.state))).length,
      done: (tasks ?? []).filter((t) => DONE.has(String(t.state))).length,
    }),
    [tasks],
  )

  if (error) {
    return (
      <div className="bots-page">
        <header className="bots-header">
          <div className="bots-title">
            <Zap size={32} />
            <div>
              <h1>Tasks</h1>
              <p>Missions and background work Jaeger is running for you</p>
            </div>
          </div>
        </header>
        <div className="bots-empty">
          <Zap size={64} />
          <h3>Tasks aren’t available</h3>
          <p>{error}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="bots-page">
      {/* Header — same structure as Browse Bots */}
      <header className="bots-header">
        <div className="bots-header__top">
          <div className="bots-title">
            <Zap size={32} />
            <div>
              <h1>Tasks</h1>
              <p>
                {tasks === null
                  ? 'Reading tasks from the gateway…'
                  : `${stats.total} tasks — the ones marked “needs you” are waiting on your decision`}
              </p>
            </div>
          </div>
        </div>

        {/* Stat filters */}
        <div className="bots-stats">
          <button className={`stat-btn${filter === 'all' ? ' active' : ''}`} onClick={() => setFilter('all')}>
            <span className="stat-btn__value">{stats.total}</span>
            <span className="stat-btn__label">All Tasks</span>
          </button>
          <button className={`stat-btn${filter === 'needs' ? ' active' : ''}`} onClick={() => setFilter('needs')}>
            <span className="stat-btn__value">{stats.needs}</span>
            <span className="stat-btn__label">Needs You</span>
          </button>
          <button className={`stat-btn${filter === 'working' ? ' active' : ''}`} onClick={() => setFilter('working')}>
            <span className="stat-btn__value">{stats.working}</span>
            <span className="stat-btn__label">Working</span>
          </button>
          <button className={`stat-btn${filter === 'done' ? ' active' : ''}`} onClick={() => setFilter('done')}>
            <span className="stat-btn__value">{stats.done}</span>
            <span className="stat-btn__label">Finished</span>
          </button>
        </div>

        {/* Search */}
        <div className="bots-search">
          <Search size={18} />
          <input
            type="text"
            placeholder="Search tasks by objective, id, or bot..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button
              className="bots-search__clear"
              onClick={() => setSearchQuery('')}
              aria-label="Clear search"
            >
              ×
            </button>
          )}
        </div>
      </header>

      {/* Task grid */}
      <div className="bots-grid-container">
        {tasks === null ? (
          <div className="bots-empty">
            <Zap size={64} />
            <h3>Reading tasks…</h3>
          </div>
        ) : filteredTasks.length === 0 ? (
          <div className="bots-empty">
            <Zap size={64} />
            <h3>No tasks found</h3>
            <p>Try a different search or filter</p>
            <button
              className="bot-card__btn bot-card__btn--primary"
              onClick={() => {
                setSearchQuery('')
                setFilter('all')
              }}
            >
              Clear filters
            </button>
          </div>
        ) : (
          <div className="bots-grid">
            {TEMPLATE_LIMIT !== Infinity && (tasks?.length ?? 0) > TEMPLATE_LIMIT && (
              <p className="bots-grid__note" role="note">
                Template preview: showing 1 of {stats.total} tasks. Real counts in the filters above; nothing was deleted.
              </p>
            )}
            {filteredTasks.map((task) => (
              <TaskCard key={task.task_id} task={task} onClick={() => setSelectedTask(task)} />
            ))}
          </div>
        )}
      </div>

      {/* Task detail modal — same frame as the character modal */}
      {selectedTask && <TaskModal task={selectedTask} onClose={() => setSelectedTask(null)} />}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// Task Card — same anatomy as CharacterCard
// ─────────────────────────────────────────────────────────────

function TaskCard({ task, onClick }: { task: Task; onClick: () => void }) {
  const needsYou = NEEDS_YOU.has(String(task.state))
  const runs = Array.isArray(task.run_history) ? task.run_history.length : 0
  const updated = timeAgo(task.updated_at)
  const { tag } = splitGoalTag(task.goal)

  return (
    <div
      className="bot-card task-card"
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick()
        }
      }}
      aria-label={`Task: ${task.goal ?? task.task_id}`}
    >
      {/* Status header: dot + state + age — the glance row */}
      <div className="task-card__head">
        <span className={`task-card__dot ${stateDotClass(task.state)}`} aria-hidden="true" />
        <span className="task-card__state">{stateLabel(task.state)}</span>
        {needsYou && <span className="task-card__chip task-card__chip--needs">needs you</span>}
        {updated && <span className="task-card__age">{updated}</span>}
      </div>

      {/* Objective: single-line title with ellipsis (Linear/GitHub card style).
          The leading [tag] renders as a chip; full text in the modal. */}
      <div className="task-card__title-row">
        {tag && <span className="task-card__chip task-card__chip--tag" title={tag}>{tag}</span>}
        <p className="task-card__goal" title={(task.goal ?? task.task_id)}>
          {goalTitle(task.goal, task.task_id)}
        </p>
      </div>

      {/* Glance metrics — only what the gateway actually reports */}
      {(runs > 0 || task.eta || task.error || task.result != null || task.presentation?.pinned) && (
        <div className="task-card__metrics">
          {runs > 0 && <span className="task-card__metric"><strong>{runs}</strong> run{runs === 1 ? '' : 's'}</span>}
          {task.eta && <span className="task-card__metric">ETA {task.eta}</span>}
          {task.error && <span className="task-card__metric task-card__metric--error">has error</span>}
          {task.result != null && <span className="task-card__metric task-card__metric--result">result</span>}
          {task.presentation?.pinned && <span className="task-card__metric">pinned</span>}
        </div>
      )}

      {/* Footer: owning bot + task id */}
      <div className="task-card__foot">
        {task.owning_agent && (
          <span className="task-card__chip">{task.owning_agent.replace(/^native:/, '')}</span>
        )}
        <span className="task-card__foot-id">{task.task_id.slice(0, 12)}</span>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// Task Modal — same frame as CharacterModal
// ─────────────────────────────────────────────────────────────

function TaskModal({ task, onClose }: { task: Task; onClose: () => void }) {
  const history = Array.isArray(task.run_history) ? task.run_history : []
  const runs = history.length

  return (
    <div className="bot-modal-overlay" onClick={onClose}>
      <div className="bot-modal task-modal" onClick={(e) => e.stopPropagation()}>
        <button className="bot-modal__close" onClick={onClose} aria-label="Close">
          <X size={20} />
        </button>

        <div className="bot-modal__layout">
          {/* Left: state + run summary */}
          <div className="bot-modal__image task-card__hero">
            <div className="task-card__hero-inner">
              <span className={`task-card__dot ${stateDotClass(task.state)}`} style={{ width: 20, height: 20 }} />
              <span className="task-card__state">{stateLabel(task.state)}</span>
              {runs > 0 && <span className="task-card__metric"><strong>{runs}</strong> runs</span>}
            </div>
          </div>

          {/* Right: everything the gateway recorded */}
          <div className="bot-modal__content">
            <div className="bot-modal__header">
              <h2 className="task-modal__goal">{task.goal ?? task.task_id}</h2>
            </div>

            <div className="task-modal__meta">
              <div>
                <span className="task-modal__meta-label">Task ID</span>
                <code>{task.task_id}</code>
              </div>
              <div>
                <span className="task-modal__meta-label">Owning agent</span>
                <span>{task.owning_agent ?? task.agent_id ?? '—'}</span>
              </div>
              <div>
                <span className="task-modal__meta-label">Origin session</span>
                <span>{task.provenance?.session_id ?? 'None recorded'}</span>
              </div>
              <div>
                <span className="task-modal__meta-label">Last update</span>
                <span>{task.updated_at ? new Date(task.updated_at * 1000).toLocaleString() : 'Unknown'}</span>
              </div>
            </div>

            {task.error && (
              <div className="bot-modal__section task-modal__error" role="alert">
                <h4>Issue</h4>
                <p>{task.error}</p>
              </div>
            )}

            <div className="bot-modal__section">
              <h4>Execution history ({history.length})</h4>
              {history.length === 0 ? (
                <p className="task-modal__muted">No runs recorded yet.</p>
              ) : (
                <p className="task-modal__muted">{history.length} run(s) recorded.</p>
              )}
            </div>

            {task.result != null && (
              <div className="bot-modal__section">
                <h4>Result</h4>
                <pre className="task-modal__result">
                  {typeof task.result === 'string' ? task.result : JSON.stringify(task.result, null, 2)}
                </pre>
              </div>
            )}

            <div className="bot-modal__footer">
              <button className="bot-card__btn" onClick={onClose}>
                Close
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default TasksPage