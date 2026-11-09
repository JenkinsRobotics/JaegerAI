import { afterEach, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Board } from './StudioPage';
import { ToastProvider } from './ui';
import type { JaegerSource } from '../api/source';
const api = vi.hoisted(() => ({ get: vi.fn(), send: vi.fn() }));
vi.mock('./webui', () => ({ getJson: api.get, sendJson: api.send }));
let root: Root;
let el: HTMLDivElement;
const baseRevision = 'a'.repeat(64);
let receiptNumber = 1;
const receipt = (_method: unknown, _path: unknown, body: { items: unknown[] }) => Promise.resolve({ items: body.items.map((i: any) => ({ ...i, x: Math.round(i.x), y: Math.round(i.y), w: Math.round(i.w), h: Math.round(i.h), ...(i.kind === 'note' ? { color: i.color ?? 'yellow' } : {}) })), updated_at: receiptNumber, revision: (++receiptNumber).toString(16).padStart(64, '0') });
const existing = { id: 'existing', kind: 'note', text: 'Keep me', x: 1, y: 1, w: 200, h: 140, color: 'yellow' };
const button = (text: string) => Array.from(el.querySelectorAll('button')).find(b => b.textContent === text)!;
async function render(source?: JaegerSource) {
  if (!el) { el = document.createElement('div'); document.body.append(el); root = createRoot(el); }
  await act(async () => root.render(<ToastProvider><Board assets={[]} source={source} /></ToastProvider>));
}
afterEach(async () => { if (root) await act(async () => root.unmount()); el = undefined!; vi.useRealTimers(); vi.resetAllMocks(); document.body.innerHTML = ''; });

it('blocks pending writes and accepts only the loaded board', async () => {
  vi.useFakeTimers();
  let resolve!: (value: unknown) => void;
  api.get.mockImplementation(() => new Promise(r => { resolve = r; })); api.send.mockImplementation(receipt);
  await render();
  expect(button('Add note').disabled).toBe(true);
  await act(async () => { button('Add note').click(); await vi.advanceTimersByTimeAsync(650); });
  expect(api.send).not.toHaveBeenCalled(); expect(el.querySelectorAll('textarea')).toHaveLength(0);
  await act(async () => resolve({ items: [existing], revision: baseRevision }));
  await act(async () => button('Add note').click());
  await act(async () => vi.advanceTimersByTimeAsync(650));
  expect(api.send.mock.calls[0][2].items[0]).toEqual(existing);
  expect(api.send.mock.calls[0][2].items).toHaveLength(2);
});
it.each([null, {}, { items: null }, { items: [null] }, { items: [{ ...existing, x: 'bad' }] }, { items: [existing, existing] }])('rejects malformed response %j', async value => {
  api.get.mockResolvedValue(value); await render();
  expect(el.textContent).toContain('Invalid board data'); expect(button('Add note').disabled).toBe(true);
  expect(button('Retry loading board')).toBeTruthy(); expect(api.send).not.toHaveBeenCalled();
});
it('retries failed load without turning failure into an empty writable board', async () => {
  api.get.mockRejectedValueOnce(new Error('Read failed')).mockResolvedValueOnce({ items: [existing], revision: baseRevision });
  await render(); expect(el.textContent).toContain('Read failed'); expect(button('Add note').disabled).toBe(true);
  await act(async () => button('Retry loading board').click());
  expect(el.querySelector('textarea')?.value).toBe('Keep me'); expect(button('Add note').disabled).toBe(false);
});
it('ignores an old source completion after the new source loads and is edited', async () => {
  vi.useFakeTimers(); let resolve!: (value: unknown) => void;
  api.get.mockImplementationOnce(() => new Promise(r => { resolve = r; })).mockResolvedValueOnce({ items: [existing], revision: baseRevision }); api.send.mockImplementation(receipt);
  await render({} as JaegerSource); await render({} as JaegerSource);
  await act(async () => button('Add note').click());
  await act(async () => resolve({ items: [], revision: 'missing' }));
  expect(el.querySelectorAll('textarea')).toHaveLength(2);
  await act(async () => vi.advanceTimersByTimeAsync(650)); expect(api.send.mock.calls[0][2].items).toHaveLength(2);
});
it('aborts unmounted reads and permits a genuinely empty successful load', async () => {
  vi.useFakeTimers(); api.get.mockResolvedValue({ items: [], revision: 'missing' }); api.send.mockImplementation(receipt);
  await render(); const signal = api.get.mock.calls[0][1] as AbortSignal;
  await act(async () => button('Add note').click()); await act(async () => vi.advanceTimersByTimeAsync(650));
  expect(api.send).toHaveBeenCalledTimes(1); await act(async () => root.unmount()); expect(signal.aborted).toBe(true);
});
it('surfaces save failure after valid loaded editing', async () => {
  vi.useFakeTimers(); api.get.mockResolvedValue({ items: [existing], revision: baseRevision }); api.send.mockRejectedValue(new Error('Disk full'));
  await render(); await act(async () => button('Add note').click()); await act(async () => vi.advanceTimersByTimeAsync(650));
  expect(document.body.textContent).toContain('Board not saved: Disk full'); expect(el.querySelectorAll('textarea')).toHaveLength(2);
});
it('ignores stale source errors and late completions after unmount', async () => {
  let reject!: (reason: Error) => void;
  let resolve!: (value: unknown) => void;
  api.get.mockImplementationOnce(() => new Promise((_r, j) => { reject = j; }))
    .mockResolvedValueOnce({ items: [existing], revision: baseRevision })
    .mockImplementationOnce(() => new Promise(r => { resolve = r; }));
  await render({} as JaegerSource); await render({} as JaegerSource);
  await act(async () => reject(new Error('Stale read failed')));
  expect(el.textContent).not.toContain('Stale read failed'); expect(el.querySelector('textarea')?.value).toBe('Keep me');
  await render({} as JaegerSource); const signal = api.get.mock.calls[2][1] as AbortSignal;
  await act(async () => root.unmount()); await act(async () => resolve({ items: [existing], revision: baseRevision }));
  expect(signal.aborted).toBe(true); expect(el.textContent).toBe(''); expect(api.send).not.toHaveBeenCalled();
});
it('persists loaded text edits, keyboard moves and removal', async () => {
  vi.useFakeTimers(); api.get.mockResolvedValue({ items: [existing], revision: baseRevision }); api.send.mockImplementation(receipt);
  await render();
  const textarea = el.querySelector('textarea')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(textarea, 'Edited');
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
    el.querySelector('.jg-board-item')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
  });
  await act(async () => vi.advanceTimersByTimeAsync(650));
  expect(api.send.mock.calls[0][2].items[0]).toMatchObject({ text: 'Edited', x: 9 });
  await act(async () => el.querySelector<HTMLButtonElement>('[aria-label="Remove from board"]')!.click());
  await act(async () => vi.advanceTimersByTimeAsync(650));
  expect(api.send.mock.calls[1][2].items).toEqual([]);
});
it('gates the asset picker until loaded, then appends a real library asset', async () => {
  vi.useFakeTimers(); let resolve!: (value: unknown) => void;
  api.get.mockImplementation(() => new Promise(r => { resolve = r; })); api.send.mockImplementation(receipt);
  await render();
  const assets = [{ id: 'asset-one', name: 'Existing image', mime: 'image/png', size: 10, created_at: 1, source: 'imported', tags: [] }];
  await act(async () => root.render(<ToastProvider><Board assets={assets} /></ToastProvider>));
  expect(button('Add asset').disabled).toBe(true);
  await act(async () => button('Add asset').click()); expect(el.textContent).not.toContain('Add an asset to the board');
  await act(async () => resolve({ items: [existing], revision: baseRevision })); await act(async () => button('Add asset').click());
  await act(async () => document.querySelector<HTMLButtonElement>('.jg-studio__tile')!.click());
  await act(async () => vi.advanceTimersByTimeAsync(650));
  expect(api.send.mock.calls[0][2].items).toHaveLength(2);
  expect(api.send.mock.calls[0][2].items[1]).toMatchObject({ kind: 'asset', asset_id: 'asset-one' });
});

it('serializes pending snapshots and coalesces intermediate edits into the latest board', async () => {
  vi.useFakeTimers();
  let acknowledge!: (value: unknown) => void;
  api.get.mockResolvedValue({ items: [], revision: 'missing' });
  api.send.mockImplementationOnce(() => new Promise<unknown>(resolve => { acknowledge = resolve; })).mockImplementation(receipt);
  await render();
  await act(async () => button('Add note').click());
  await act(async () => vi.advanceTimersByTimeAsync(650));
  await act(async () => button('Add note').click());
  await act(async () => vi.advanceTimersByTimeAsync(650));
  await act(async () => button('Add note').click());
  await act(async () => vi.advanceTimersByTimeAsync(650));
  expect(api.send).toHaveBeenCalledTimes(1);
  expect(api.send.mock.calls[0][2].items).toHaveLength(1);
  await act(async () => acknowledge(await receipt(...api.send.mock.calls[0] as [unknown, unknown, { items: unknown[] }])));
  await act(async () => vi.advanceTimersByTimeAsync(650));
  expect(api.send).toHaveBeenCalledTimes(2);
  expect(api.send.mock.calls[1][2].items).toHaveLength(3);
  await act(async () => vi.advanceTimersByTimeAsync(5000));
  expect(api.send).toHaveBeenCalledTimes(2);
});

it.each(['rejected', 'response lost after commit'])('pauses queued and later saves after %s, retaining all local edits and warning', async outcome => {
  vi.useFakeTimers();
  let fail!: (e: Error) => void;
  api.get.mockResolvedValue({ items: [], revision: 'missing' });
  api.send.mockImplementation(() => new Promise((_resolve, reject) => { fail = reject; }));
  await render();
  await act(async () => button('Add note').click());
  await act(async () => vi.advanceTimersByTimeAsync(650));
  await act(async () => button('Add note').click());
  await act(async () => vi.advanceTimersByTimeAsync(650));
  await act(async () => fail(new Error(outcome)));
  await act(async () => button('Add note').click());
  await act(async () => vi.advanceTimersByTimeAsync(10000));
  expect(api.send).toHaveBeenCalledTimes(1);
  expect(el.querySelectorAll('textarea')).toHaveLength(3);
  expect(el.querySelector('[role="alert"]')?.textContent).toContain('Automatic saving is paused');
  expect(el.textContent).not.toContain('Changes save automatically.');
});

it('keeps the latest edit when acknowledgment precedes its debounce', async () => {
  vi.useFakeTimers();
  let acknowledge!: (value: unknown) => void;
  api.get.mockResolvedValue({ items: [], revision: 'missing' });
  api.send.mockImplementationOnce(() => new Promise<unknown>(resolve => { acknowledge = resolve; })).mockImplementation(receipt);
  await render();
  await act(async () => button('Add note').click());
  await act(async () => vi.advanceTimersByTimeAsync(650));
  await act(async () => button('Add note').click());
  await act(async () => acknowledge(await receipt(...api.send.mock.calls[0] as [unknown, unknown, { items: unknown[] }])));
  await act(async () => vi.advanceTimersByTimeAsync(650));
  expect(api.send).toHaveBeenCalledTimes(2);
  expect(api.send.mock.calls[1][2].items).toHaveLength(2);
});

it('keeps two mounted clients separate: a stale rejected root retains edits and never retries', async () => {
  vi.useFakeTimers();
  let saved = { items: [existing], revision: baseRevision, updated_at: 1 };
  api.get.mockImplementation(async () => structuredClone(saved));
  api.send.mockImplementation(async (_method, _path, body) => {
    if (body.expected_revision !== saved.revision) throw new Error('Board changed; reload and reconcile your edits');
    saved = { items: structuredClone(body.items), revision: 'b'.repeat(64), updated_at: 2 };
    return structuredClone(saved);
  });
  await render();
  const other = document.createElement('div'); document.body.append(other); const second = createRoot(other);
  try {
    await act(async () => second.render(<ToastProvider><Board assets={[]} /></ToastProvider>));
    await act(async () => button('Add note').click());
    await act(async () => vi.advanceTimersByTimeAsync(650));
    const committed = structuredClone(saved);
    const addOther = () => Array.from(other.querySelectorAll('button')).find(b => b.textContent === 'Add note')!.click();
    await act(async () => addOther());
    await act(async () => vi.advanceTimersByTimeAsync(650));
    expect(saved).toEqual(committed);
    expect(other.querySelectorAll('textarea')).toHaveLength(2);
    expect(other.textContent).toContain('Board changed');
    await act(async () => addOther());
    await act(async () => vi.advanceTimersByTimeAsync(10000));
    expect(other.querySelectorAll('textarea')).toHaveLength(3);
    expect(other.textContent).toContain('Automatic saving is paused');
    expect(api.send).toHaveBeenCalledTimes(2);
    expect(api.send.mock.calls[1][2].expected_revision).toBe(baseRevision);
  } finally { await act(async () => second.unmount()); }
});

it.each([{}, { items: [], revision: 'b'.repeat(64), updated_at: 2 },
  { items: [existing], revision: 'missing', updated_at: 2 },
  { items: [existing], revision: baseRevision, updated_at: 2 }])('does not unlock queued or later writes after malformed acknowledgment %j', async value => {
  vi.useFakeTimers(); api.get.mockResolvedValue({ items: [existing], revision: baseRevision });
  let resolve!: (value: unknown) => void;
  api.send.mockImplementation(() => new Promise(r => { resolve = r; }));
  await render();
  await act(async () => button('Add note').click());
  await act(async () => vi.advanceTimersByTimeAsync(650));
  await act(async () => button('Add note').click());
  await act(async () => resolve(value));
  await act(async () => button('Add note').click());
  await act(async () => vi.advanceTimersByTimeAsync(10000));
  expect(api.send).toHaveBeenCalledTimes(1);
  expect(el.querySelectorAll('textarea')).toHaveLength(4);
  expect(el.textContent).toContain('Automatic saving is paused');
});

it('advances the acknowledged base for coalesced edits and adopts normalized state', async () => {
  vi.useFakeTimers(); api.get.mockResolvedValue({ items: [{ ...existing, x: 1.5 }], revision: baseRevision });
  let resolve!: (value: unknown) => void;
  api.send.mockImplementationOnce(() => new Promise(r => { resolve = r; })).mockImplementation(receipt);
  await render();
  await act(async () => button('Add note').click());
  await act(async () => vi.advanceTimersByTimeAsync(650));
  await act(async () => button('Add note').click());
  const normalized = api.send.mock.calls[0][2].items.map((i: typeof existing) => ({ ...i, x: Math.round(i.x) }));
  await act(async () => resolve({ items: normalized, revision: 'c'.repeat(64), updated_at: 2 }));
  await act(async () => vi.advanceTimersByTimeAsync(650));
  expect(api.send).toHaveBeenCalledTimes(2);
  expect(api.send.mock.calls[0][2].expected_revision).toBe(baseRevision);
  expect(api.send.mock.calls[1][2].expected_revision).toBe('c'.repeat(64));
  expect(api.send.mock.calls[1][2].items).toHaveLength(3);
  expect((el.querySelector('.jg-board-item') as HTMLElement).style.left).toBe('2px');
  expect(el.textContent).not.toContain('Automatic saving is paused');
});

it('accepts producer codepoint truncation and ties-to-even normalization without losing acknowledgment', async () => {
  vi.useFakeTimers();
  const text = '😀'.repeat(3999) + 'XY';
  api.get.mockResolvedValue({ items: [{ ...existing, text, x: 2.5, y: -2.5 }], revision: baseRevision });
  api.send.mockImplementation(async (_method, _path, body) => ({
    items: body.items.map((i: typeof existing) => i.id === existing.id ? { ...i, text: '😀'.repeat(3999) + 'X', x: 2, y: -2 } : i),
    revision: 'd'.repeat(64), updated_at: 2,
  }));
  await render();
  await act(async () => button('Add note').click());
  await act(async () => vi.advanceTimersByTimeAsync(650));
  expect(el.querySelector('textarea')!.value).toBe('😀'.repeat(3999) + 'X');
  expect((el.querySelector('.jg-board-item') as HTMLElement).style.left).toBe('2px');
  expect((el.querySelector('.jg-board-item') as HTMLElement).style.top).toBe('-2px');
  expect(el.textContent).not.toContain('Automatic saving is paused');
});
