import { afterEach, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { FirstRunGate, FirstRunPage, type FirstRunApi, type FirstRunStatus } from './FirstRun';

const pending: FirstRunStatus = { status: 'NOT_STARTED', completed: false, skipped: false, character_id: null, model_selection: null };
const completed: FirstRunStatus = { ...pending, status: 'COMPLETED', completed: true };
let root: Root | undefined;
let el: HTMLDivElement | undefined;
afterEach(() => { if (root) act(() => root!.unmount()); el?.remove(); history.replaceState(null, '', '/'); });
function api(status = pending): FirstRunApi {
  return { status: vi.fn(async () => status), setup: vi.fn(async () => completed), skip: vi.fn(async () => ({ ...completed, skipped: true })), models: vi.fn(async () => ({ providers: [{ id: 'ollama', display_name: 'Ollama', configured: true, reachable: true, models: [{ id: 'qwen3:4b' }] }] })) };
}
async function mount(node: React.ReactNode) { el = document.createElement('div'); document.body.append(el); root = createRoot(el); await act(async () => { root!.render(node); }); return el; }
async function click(button: HTMLButtonElement) { await act(async () => { button.click(); }); }
function button(label: string) { const found = [...el!.querySelectorAll('button')].find((item) => item.textContent?.trim() === label); if (!found) throw Error(`Missing ${label}`); return found; }

it('shows first run on Home when NOT_STARTED', async () => {
  history.replaceState(null, '', '/');
  await mount(<FirstRunGate api={api()}><div>Home content</div></FirstRunGate>);
  expect(location.pathname).toBe('/first-run'); expect(el!.textContent).toContain('Welcome to Jaeger'); expect(el!.textContent).not.toContain('Home content');
});
it('hides first run when COMPLETED', async () => {
  history.replaceState(null, '', '/first-run');
  await mount(<FirstRunGate api={api(completed)}><div>Home content</div></FirstRunGate>);
  expect(location.pathname).toBe('/'); expect(el!.textContent).toContain('Home content');
});
it('posts exactly character, awake provider and awake model', async () => {
  const client = api(); await mount(<FirstRunPage api={client} onDone={vi.fn()} />);
  await click(button('Get started'));
  await click(el!.querySelector('.jg-first-run__characters button')!);
  await click(button('Choose character'));
  const selects = el!.querySelectorAll('select');
  await act(async () => { selects[0].value = 'ollama'; selects[0].dispatchEvent(new Event('change', { bubbles: true })); });
  await act(async () => { selects[1].value = 'qwen3:4b'; selects[1].dispatchEvent(new Event('change', { bubbles: true })); });
  await click(button('Connect models'));
  expect(client.setup).toHaveBeenCalledExactlyOnceWith({ character_id: expect.any(String), awake_provider: 'ollama', awake_model: 'qwen3:4b' });
});
it('posts skip and hides the page', async () => {
  history.replaceState(null, '', '/'); const client = api();
  await mount(<FirstRunGate api={client}><div>Home content</div></FirstRunGate>);
  await click(button('Skip setup'));
  expect(client.skip).toHaveBeenCalledOnce(); expect(el!.textContent).toContain('Home content');
});
it('shows setup errors', async () => {
  const client = api(); vi.mocked(client.setup).mockRejectedValue(Error('Model unavailable'));
  await mount(<FirstRunPage api={client} onDone={vi.fn()} />);
  await click(button('Get started')); await click(el!.querySelector('.jg-first-run__characters button')!); await click(button('Choose character'));
  const selects = el!.querySelectorAll('select');
  await act(async () => { selects[0].value = 'ollama'; selects[0].dispatchEvent(new Event('change', { bubbles: true })); });
  await act(async () => { selects[1].value = 'qwen3:4b'; selects[1].dispatchEvent(new Event('change', { bubbles: true })); });
  await click(button('Connect models'));
  expect(el!.querySelector('[role="alert"]')?.textContent).toContain('Model unavailable');
});
it('fails open to the app when first-run status cannot load', async () => {
  history.replaceState(null, '', '/'); const client = { ...api(), status: vi.fn(async () => { throw Error('404'); }) };
  await mount(<FirstRunGate api={client}><div>Home content</div></FirstRunGate>);
  expect(location.pathname).toBe('/'); expect(el!.textContent).toContain('Home content');
});
