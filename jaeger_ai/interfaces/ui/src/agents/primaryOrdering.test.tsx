import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it } from 'vitest';
import { useAgentsStore, loadRoster } from './agentsStore';
import { MockSource } from '../api/mock';
import type { Agent } from '../api/types';
import { sidebarRows } from './agentsLogic';
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const deferred = () => { let resolve!: (a: Agent[]) => void; const promise = new Promise<Agent[]>((r) => { resolve = r; }); return { promise, resolve }; };
const a: Agent = { id: 'native:owned-a', name: 'Jaeger', role: 'specialist', primary: true };
const b: Agent = { id: 'native:owned-b', name: 'Other', role: 'specialist', primary: false };
it('ignores older roster response after a later primary refresh; alias/order/lead role do not select primary', async () => {
  const pending = [deferred(), deferred(), deferred()]; let call = 0;
  const source = new MockSource(); source.agents = () => pending[call++].promise; source.agentsSummary = async () => [];
  let refresh!: () => Promise<void>;
  const Harness = () => { const state = useAgentsStore(source); refresh = state.refresh; return <span>{state.agents.find((x) => x.primary)?.id}</span>; };
  const el = document.createElement('div'); document.body.append(el); const root = createRoot(el);
  try {
    await act(async () => root.render(<Harness />));
    await act(async () => { pending[0].resolve([a,b]); });
    let old!: Promise<void>; let latest!: Promise<void>;
    await act(async () => { old = refresh(); latest = refresh(); });
    const updated = [{ ...b, name: 'Renamed', primary: true }, { ...a, role: 'lead', primary: false }];
    await act(async () => { pending[2].resolve(updated); await latest; });
    expect(el.textContent).toBe(b.id);
    await act(async () => { pending[1].resolve([a,b]); await old; });
    expect(el.textContent).toBe(b.id);
    expect(sidebarRows(updated, []).lead?.agent.id).toBe(b.id);
    expect(sidebarRows([{ ...a, primary: undefined, role: 'lead' }], []).lead).toBeUndefined();
  } finally { await act(async () => root.unmount()); el.remove(); }
});
it('rejects multiple-primary projection instead of picking by array order', async () => {
  await expect(loadRoster({ agents: async () => [a,{...b,primary:true}], agentsSummary: async () => [] })).rejects.toThrow('multiple primary');
});
