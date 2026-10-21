import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect, it, vi} from 'vitest';
import {WorkflowRuns} from './WorkflowRuns';
import type {JaegerSource, WorkflowRun} from '../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
const row: WorkflowRun = {task_id: 'owned-run', state: 'paused', authorized: false, workflow_revision: 2, workflow_digest: 'fixture', origin_session_id: 'owned-home', updated_at: 1, result: null, error: null, request_status: null};
it('reads approval, canonical unknown and result without creating or retrying a run', async () => {
  const runs = vi.fn().mockResolvedValueOnce({workflow_id: 'owned', runs: [row]})
    .mockResolvedValueOnce({workflow_id: 'owned', runs: [{...row, state: 'completed', authorized: true, request_status: 'execution_unknown'}]})
    .mockResolvedValueOnce({workflow_id: 'owned', runs: [{...row, state: 'completed_verified', authorized: true, request_status: 'completed', result: {output: 'Owner checked result', evidence: {checked: true}} }]});
  const mutate = vi.fn();
  const source = {workflows: {runs, mutate}} as unknown as JaegerSource;
  const element = document.createElement('div'); document.body.append(element); const root = createRoot(element);
  await act(async () => root.render(<WorkflowRuns source={source} workflowId="owned" refresh={0}/>));
  expect(element.textContent).toContain('Awaiting task approval');
  const refresh = () => element.querySelector('button')!;
  await act(async () => refresh().click());
  expect(element.textContent).toContain('Do not replay this run');
  await act(async () => refresh().click());
  expect(element.textContent).toContain('Owner checked result');
  expect(element.querySelector('pre')?.textContent).toBe(JSON.stringify({output: 'Owner checked result', evidence: {checked: true}}, null, 2));
  expect(element.textContent).not.toContain('Do not replay this run');
  expect(mutate).not.toHaveBeenCalled();
  expect(runs.mock.calls).toEqual([['owned'], ['owned'], ['owned']]);
  await act(async () => root.unmount()); element.remove();
});
it('discards prior workflow results during navigation and on disconnect', async () => {
  let resolve!: (value: unknown) => void;
  const runs = vi.fn().mockResolvedValueOnce({workflow_id: 'first', runs: [{...row, result: 'First private result'}]})
    .mockImplementationOnce(() => new Promise(r => {resolve = r;}))
    .mockRejectedValueOnce(Error('Disconnected'));
  const source = {workflows: {runs}} as unknown as JaegerSource;
  const element = document.createElement('div'); document.body.append(element); const root = createRoot(element);
  await act(async () => root.render(<WorkflowRuns source={source} workflowId="first" refresh={0}/>));
  expect(element.textContent).toContain('First private result');
  await act(async () => root.render(<WorkflowRuns source={source} workflowId="second" refresh={0}/>));
  expect(element.textContent).not.toContain('First private result');
  await act(async () => resolve({workflow_id: 'first', runs: [row]}));
  expect(element.textContent).toContain('identity mismatch');
  await act(async () => element.querySelector('button')!.click());
  expect(element.textContent).toContain('Disconnected');
  expect(element.textContent).not.toContain('owned-run');
  await act(async () => root.unmount()); element.remove();
});
