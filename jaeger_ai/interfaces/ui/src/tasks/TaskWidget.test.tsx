import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { TaskWidget, computeTaskProgress } from './TaskWidget';
import type { Task, Agent } from '../api/types';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const roots: ReturnType<typeof createRoot>[] = [];

afterEach(async () => {
  await act(async () => roots.splice(0).forEach((r) => r.unmount()));
  document.body.innerHTML = '';
});

function renderWidget(task: Task, agents: Agent[] = [], onSelect = vi.fn()) {
  const el = document.createElement('div');
  document.body.append(el);
  const root = createRoot(el);
  roots.push(root);
  act(() => {
    root.render(<TaskWidget task={task} agents={agents} onSelect={onSelect} />);
  });
  return { el, onSelect };
}

it('computes correct progress percentage across states', () => {
  expect(computeTaskProgress({ task_id: '1', state: 'completed' }).percent).toBe(100);
  expect(computeTaskProgress({ task_id: '2', state: 'failed' }).percent).toBe(100);
  expect(computeTaskProgress({ task_id: '3', state: 'queued' }).percent).toBe(5);
  expect(computeTaskProgress({ task_id: '4', state: 'running', run_history: [{}, {}] }).percent).toBe(50);
});

it('renders task goal, agent, progress bar and triggers onSelect when clicked', async () => {
  const onSelect = vi.fn();
  const task: Task = {
    task_id: 'task-12345',
    goal: 'Calibrate arm kinematics',
    state: 'running',
    agent_id: 'agent-1',
    eta: '30s',
    run_history: [{}],
  };
  const agents: Agent[] = [{ id: 'agent-1', name: 'Kinematics Lead' }];

  const { el } = renderWidget(task, agents, onSelect);

  expect(el.textContent).toContain('Calibrate arm kinematics');
  expect(el.textContent).toContain('Kinematics Lead');
  expect(el.textContent).toContain('ETA 30s');
  expect(el.querySelector('.jg-task-widget__progress-bar')).not.toBeNull();

  const card = el.querySelector('[role="button"]') as HTMLElement;
  await act(async () => card.click());

  expect(onSelect).toHaveBeenCalledWith('task-12345');
});

