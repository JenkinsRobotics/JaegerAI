import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { TaskInspector } from './TaskInspector';
import type { Task } from '../api/types';
import type { JaegerSource } from '../api/source';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const roots: ReturnType<typeof createRoot>[] = [];

afterEach(async () => {
  await act(async () => roots.splice(0).forEach((r) => r.unmount()));
  document.body.innerHTML = '';
});

function renderInspector(task: Task, source: Partial<JaegerSource> = {}, onClose = vi.fn()) {
  const el = document.createElement('div');
  document.body.append(el);
  const root = createRoot(el);
  roots.push(root);
  act(() => {
    root.render(
      <TaskInspector
        task={task}
        agents={[{ id: 'lead', name: 'Jaeger Lead' }]}
        source={source as JaegerSource}
        onClose={onClose}
      />
    );
  });
  return { el, onClose };
}

it('renders overview tab with task details, origin provenance and result', () => {
  const task: Task = {
    task_id: 'task-inspect-1',
    goal: 'Generate CAD model for sensor mount',
    state: 'completed',
    agent_id: 'lead',
    provenance: { session_id: 'sess-99', request_id: 'req-42' },
    result: { status: 'success', file: 'mount.step' },
  };

  const { el } = renderInspector(task);

  expect(el.textContent).toContain('Generate CAD model for sensor mount');
  expect(el.textContent).toContain('task-inspect-1');
  expect(el.textContent).toContain('sess-99');
  expect(el.textContent).toContain('req-42');
  expect(el.textContent).toContain('mount.step');
});

it('switches between tabs and displays execution steps', async () => {
  const task: Task = {
    task_id: 'task-inspect-2',
    goal: 'Analyze motor torque',
    state: 'running',
    run_history: [
      { step: 'Load specs', tool: 'file_read' },
      { step: 'Run simulation', tool: 'pybullet' },
    ],
  };

  const { el } = renderInspector(task);
  const stepsTab = [...el.querySelectorAll('[role="tab"]')].find((t) =>
    t.textContent?.includes('Execution Steps')
  ) as HTMLElement;

  await act(async () => stepsTab.click());

  expect(el.textContent).toContain('Load specs');
  expect(el.textContent).toContain('Run simulation');
});
