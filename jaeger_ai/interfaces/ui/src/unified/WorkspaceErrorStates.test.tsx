import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { JaegerSource } from '../api/source';
import { CalendarPage } from './CalendarPage';
import { PipelinePage, ProductionPage, TaskBanner } from './PipelinePage';
import { pipelineApi, type Attachment, type PipelineRecord } from './pipeline';
import { ToastProvider } from './ui';

vi.mock('./RunnerQueue', () => ({ RunnerQueue: () => null }));
afterEach(() => vi.restoreAllMocks());
const source = (parts: object) => ({ tasks: async () => [], ...parts }) as unknown as JaegerSource;
const go = () => {};
const page = (s: JaegerSource, id = 't1') => <ToastProvider><ProductionPage source={s} params={new URLSearchParams({ task: id })} onNavigate={go} /></ToastProvider>;
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>((r) => { resolve = r; }); return { promise, resolve }; };

describe('workspace read failures', () => {
  it('reloads the preserved banner when only its page stage changes', async () => {
    const rec: PipelineRecord = { task_id: 't1', stage: 'production', revision: 1, history: [], attachments: [] };
    vi.spyOn(pipelineApi, 'list').mockResolvedValue({ stages: [], items: { t1: rec } });
    const tasks = vi.fn().mockResolvedValue([{ task_id: 't1', goal: 'Shared task' }]);
    const src = source({ tasks });
    const banner = (stage: 'production' | 'research') => <ToastProvider><TaskBanner source={src} taskId="t1" stage={stage} onNavigate={go} clearTo="/work" /></ToastProvider>;
    const view = render(banner('production'));
    await screen.findByText('Shared task');
    view.rerender(banner('research'));
    expect(await screen.findByText('Shared task')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('Attach document')).toBeEnabled());
    expect(tasks).toHaveBeenCalledTimes(2);
    expect(screen.getByLabelText('Stage: Production')).toBeInTheDocument();
  });

  it('ignores attachment completion from a previous task instead of contaminating the current record', async () => {
    const records: Record<string, PipelineRecord> = Object.fromEntries(['A', 'B'].map((task_id) => [task_id, { task_id, stage: 'studio', revision: 1, history: [], attachments: [] }]));
    const list = vi.spyOn(pipelineApi, 'list').mockResolvedValue({ stages: [], items: records });
    const pending = deferred<Attachment>();
    vi.spyOn(pipelineApi, 'attach').mockReturnValue(pending.promise);
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ assets: [{ id: 'a', name: 'A output' }] }), { status: 200 }));
    const src = source({ tasks: async () => [{ task_id: 'A', goal: 'Task A' }, { task_id: 'B', goal: 'Task B' }] });
    const banner = (taskId: string) => <ToastProvider><TaskBanner source={src} taskId={taskId} stage="studio" onNavigate={go} clearTo="/studio" /></ToastProvider>;
    const view = render(banner('A'));
    await waitFor(() => expect(screen.getByText('Attach asset')).toBeEnabled());
    fireEvent.click(screen.getByText('Attach asset'));
    fireEvent.click(await screen.findByText('A output'));
    view.rerender(banner('B'));
    await screen.findByText('Task B');
    await waitFor(() => expect(screen.getByText('Attach asset')).toBeEnabled());
    list.mockRejectedValue(new Error('refresh offline'));
    await act(async () => pending.resolve({ id: 'a', kind: 'asset', ref: 'asset:a', label: 'A output', text: null, stage: 'studio', at: 1 }));
    expect(screen.getByText('Task B')).toBeInTheDocument();
    expect(screen.queryByText('A output')).not.toBeInTheDocument();
    expect(screen.queryByText('Attached “A output”')).not.toBeInTheDocument();
    expect(list).toHaveBeenCalledTimes(2);
  });

  it('does not navigate or replace the current record after an old stage advance completes', async () => {
    const records: Record<string, PipelineRecord> = Object.fromEntries(['A', 'B'].map((task_id) => [task_id, { task_id, stage: 'studio', revision: 1, history: [], attachments: [] }]));
    vi.spyOn(pipelineApi, 'list').mockResolvedValue({ stages: [], items: records });
    const pending = deferred<PipelineRecord>();
    vi.spyOn(pipelineApi, 'setStage').mockReturnValue(pending.promise);
    const navigate = vi.fn();
    const src = source({ tasks: async () => [{ task_id: 'A', goal: 'Task A' }, { task_id: 'B', goal: 'Task B' }] });
    const banner = (taskId: string) => <ToastProvider><TaskBanner source={src} taskId={taskId} stage="studio" onNavigate={navigate} clearTo="/studio" /></ToastProvider>;
    const view = render(banner('A'));
    await waitFor(() => expect(screen.getByText('Advance to Production')).toBeEnabled());
    fireEvent.click(screen.getByText('Advance to Production'));
    view.rerender(banner('B'));
    await screen.findByText('Task B');
    await act(async () => pending.resolve({ ...records.A, stage: 'production', revision: 2 }));
    expect(screen.getByLabelText('Stage: Studio')).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
    expect(screen.queryByText('Moved to Production')).not.toBeInTheDocument();
  });

  it('surfaces banner reads that fail without claiming the task disappeared, then recovers', async () => {
    vi.spyOn(pipelineApi, 'list').mockRejectedValueOnce(new Error('pipeline offline')).mockResolvedValue({ stages: [], items: {} });
    const tasks = vi.fn().mockRejectedValueOnce(new Error('tasks offline')).mockResolvedValue([{ task_id: 't1', goal: 'Recovered task' }]);
    render(<ToastProvider><TaskBanner source={source({ tasks })} taskId="t1" stage="studio" onNavigate={go} clearTo="/studio" /></ToastProvider>);
    expect(await screen.findByRole('alert')).toHaveTextContent('Task details unavailable');
    expect(screen.queryByText(/isn’t in the gateway/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Stage: not started')).not.toBeInTheDocument();
    expect(screen.getByText('Attach asset')).toBeDisabled();
    fireEvent.click(screen.getByText('Retry task details'));
    expect(await screen.findByText('Recovered task')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('Attach asset')).toBeEnabled());
  });

  it('does not cache picker errors as no attachments and retries the failed source', async () => {
    vi.spyOn(pipelineApi, 'list').mockResolvedValue({ stages: [], items: {} });
    vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new Error('assets offline')).mockResolvedValue(new Response(JSON.stringify({ assets: [{ id: 'a', name: 'Recovered asset' }] }), { status: 200 }));
    render(<ToastProvider><TaskBanner source={source({})} taskId="t1" stage="studio" onNavigate={go} clearTo="/studio" /></ToastProvider>);
    await waitFor(() => expect(screen.getByText('Attach asset')).toBeEnabled());
    fireEvent.click(screen.getByText('Attach asset'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Attachments unavailable: assets offline');
    expect(screen.queryByText('Nothing to attach yet.')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Retry attachments'));
    expect(await screen.findByText('Recovered asset')).toBeInTheDocument();
  });

  it('reports artifact failure without claiming there are no files, then retries', async () => {
    vi.spyOn(pipelineApi, 'list').mockResolvedValue({ stages: [], items: {} });
    const list = vi.fn().mockRejectedValueOnce(new Error('artifact service offline')).mockResolvedValue({ artifacts: [] });
    render(page(source({ taskArtifacts: { list } })));
    expect(await screen.findByRole('alert')).toHaveTextContent('artifact service offline');
    expect(screen.queryByText('No files produced by this task.')).not.toBeInTheDocument();
    expect(await screen.findByText('This task is not in the current task list.')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Retry artifacts'));
    expect(await screen.findByText('No files produced by this task.')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('does not replace the selected task artifacts with a late previous response', async () => {
    vi.spyOn(pipelineApi, 'list').mockResolvedValue({ stages: [], items: {} });
    const old = deferred<{ artifacts: object[] }>();
    const list = vi.fn().mockReturnValueOnce(old.promise).mockResolvedValue({ artifacts: [{ attachment_id: 'new', name: 'New output', size: 100, mime: 'text/plain' }] });
    const s = source({ taskArtifacts: { list } });
    const view = render(page(s));
    view.rerender(page(s, 't2'));
    await screen.findByText('New output');
    await act(async () => old.resolve({ artifacts: [{ attachment_id: 'old', name: 'Old output', size: 100, mime: 'text/plain' }] }));
    expect(screen.queryByText('Old output')).not.toBeInTheDocument();
    expect(screen.getByText('New output')).toBeInTheDocument();
  });

  it('reports task due-date failure, avoids false empty agenda, and recovers on refresh', async () => {
    const tasks = vi.fn().mockRejectedValueOnce(new Error('tasks offline')).mockResolvedValue([]);
    render(<ToastProvider><CalendarPage source={source({ tasks, schedules: { list: async () => ({ jobs: [] }) } })} onNavigate={go} /></ToastProvider>);
    expect(await screen.findByRole('alert')).toHaveTextContent('Task due dates unavailable: tasks offline');
    expect(screen.queryByText('Nothing scheduled')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Refresh'));
    expect(await screen.findByText('Nothing scheduled')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('reports schedule failure without an empty agenda and recovers', async () => {
    const list = vi.fn().mockRejectedValueOnce(new Error('scheduler offline')).mockResolvedValue({ jobs: [] });
    render(<ToastProvider><CalendarPage source={source({ schedules: { list } })} onNavigate={go} /></ToastProvider>);
    expect(await screen.findByRole('alert')).toHaveTextContent('Schedules unavailable: scheduler offline');
    expect(screen.queryByText('Nothing scheduled')).not.toBeInTheDocument();
    expect(screen.queryByText('No schedules.')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Refresh'));
    expect(await screen.findByText('Nothing scheduled')).toBeInTheDocument();
    expect(screen.getByText('No schedules.')).toBeInTheDocument();
  });

  it('reports unavailable production results and deliverables instead of indefinite loading', async () => {
    vi.spyOn(pipelineApi, 'list').mockRejectedValue(new Error('pipeline offline'));
    render(page(source({})));
    expect(await screen.findByRole('alert')).toHaveTextContent('pipeline offline');
    expect(screen.getByText('Result unavailable. Refresh to retry.')).toBeInTheDocument();
    expect(screen.getByText('Deliverables unavailable. Refresh to retry.')).toBeInTheDocument();
    expect(screen.queryByText('This task is not in the current task list.')).not.toBeInTheDocument();
  });

  it('still loads task due dates without a scheduler and excludes completed tasks', async () => {
    render(<ToastProvider><CalendarPage source={source({ tasks: async () => [{ task_id: 't', goal: 'Due soon', eta: 2000000000, state: 'running' }, { task_id: 'done', goal: 'Already done', eta: 2000000000, state: 'succeeded' }] })} onNavigate={go} /></ToastProvider>);
    expect(await screen.findByText('Due soon')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('no scheduler');
    expect(screen.queryByText('Already done')).not.toBeInTheDocument();
    expect(screen.queryByText('Nothing scheduled')).not.toBeInTheDocument();
  });

  it('does not present pipeline counts or an empty state after a failed refresh', async () => {
    vi.spyOn(pipelineApi, 'list').mockResolvedValueOnce({ stages: [], items: {} }).mockRejectedValueOnce(new Error('pipeline offline')).mockResolvedValue({ stages: [], items: {} });
    render(<ToastProvider><PipelinePage source={source({})} params={new URLSearchParams()} onNavigate={go} /></ToastProvider>);
    await screen.findByText('No tasks yet');
    fireEvent.click(screen.getByText('Refresh'));
    expect(await screen.findByRole('alert')).toHaveTextContent('pipeline offline');
    expect(screen.queryByText('No tasks yet')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Tasks per stage')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Refresh'));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(await screen.findByText('No tasks yet')).toBeInTheDocument();
  });
});
