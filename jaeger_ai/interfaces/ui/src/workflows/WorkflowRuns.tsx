import {useEffect, useState} from 'react';
import type {JaegerSource, WorkflowRun} from '../api/source';
import {TaskArtifacts} from '../library/TaskArtifacts';

/** Read-only projection of the existing task/receipt owner, never a run button. */
export function WorkflowRuns({source, workflowId, refresh}: {source: JaegerSource; workflowId: string; refresh: number}) {
  const [snapshot, setSnapshot] = useState<{id: string; rows: WorkflowRun[]}>();
  const [error, setError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setSnapshot(undefined); setError(undefined);
    const load = async () => {
      try {
        const value = await source.workflows!.runs(workflowId);
        if (value.workflow_id !== workflowId) throw Error('Workflow run identity mismatch');
        if (live) {setSnapshot({id: workflowId, rows: value.runs}); setError(undefined);}
      } catch (e) {if (live) {setSnapshot(undefined); setError(String(e));}}
    };
    // No execution/retry side effect. Refresh also recovers after transport loss.
    void load();
    return () => {live = false;};
  }, [source, workflowId, refresh, attempt]);
  const rows = snapshot?.id === workflowId ? snapshot.rows : undefined;
  return <section aria-label="Workflow runs"><h3>Saved workflow runs</h3>
    <p>Tasks own approval, execution and recovery. Refresh to read their current receipts; this never retries work.</p>
    <button onClick={() => setAttempt(n => n + 1)}>Refresh workflow runs</button>
    {error && <p role="alert">Run status unavailable: {error}. Check Tasks; no run was resubmitted.</p>}
    {!error && !rows && <p role="status">Loading workflow runs…</p>}
    {rows?.length === 0 && <p>No saved run proposals for this workflow.</p>}
    {rows?.map(run => <article key={run.task_id} aria-label={`Workflow run ${run.task_id}`}>
      <p>Revision {run.workflow_revision} · {run.task_id} · Task state: {run.state}</p>
      <p>{run.authorized ? 'Task approved; tool approvals still apply.' : run.state === 'paused' && !run.request_status ? 'Awaiting task approval in Tasks.' : 'Task is not authorized.'}</p>
      <p>Execution receipt: {run.request_status ?? 'No admitted execution receipt'}</p>
      {run.request_status === 'execution_unknown' && <p role="alert">Execution needs reconciliation. Do not replay this run.</p>}
      {run.error && <p role="alert">{run.error}</p>}
      {run.result != null && <pre style={{whiteSpace: 'pre-wrap'}}>{typeof run.result === 'string' ? run.result : JSON.stringify(run.result, null, 2)}</pre>}
      {source.taskArtifacts && <TaskArtifacts controls={source.taskArtifacts} taskId={run.task_id}/>}
    </article>)}
  </section>;
}
