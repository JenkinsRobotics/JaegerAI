import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { it, expect, vi } from 'vitest';
import { ToolsPanel } from './ToolsPanel';
import { PluginCatalog } from './PluginCatalog';
import { MCPResources } from './MCPResources';
import type { JaegerSource, PluginControls, MCPResources as ResourceControls } from '../api/source';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
async function mounted(render: (host: HTMLElement) => Promise<void>) {
 const host = document.createElement('div'); document.body.append(host);
 try { await render(host); } finally { host.remove(); }
}
const state = (host: HTMLElement, value: string) => host.querySelector(`.jg-widget-card[data-state="${value}"]`);

it('maps tool loading, empty, error and retained rows to cards', async () => mounted(async host => {
 const root = createRoot(host);
 const tools = vi.fn().mockResolvedValueOnce({tools:[],count:0,servers:[],mcp_initialized:true}).mockRejectedValueOnce(Error('offline'));
 try {
  await act(async () => root.render(<ToolsPanel source={{tools} as unknown as JaegerSource}/>));
  expect(state(host,'loading')?.textContent).toContain('Reading registered inventory');
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 180)); });
  expect(state(host,'empty')?.textContent).toContain('No matching registered tools');
  await act(async () => host.querySelector('button')!.click());
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 180)); });
  expect(state(host,'error')?.textContent).toContain('Previous inventory retained');
  expect(state(host,'empty')).not.toBeNull();
 } finally { await act(async () => root.unmount()); }
}));

it('maps plugin loading, empty and retained read error to cards', async () => mounted(async host => {
 const root = createRoot(host);
 let release!: (value: {plugins: []}) => void;
 const list = vi.fn().mockImplementationOnce(() => new Promise<{plugins: []}>(resolve => { release = resolve; })).mockRejectedValueOnce(Error('offline'));
 try {
  await act(async () => root.render(<PluginCatalog controls={{list} as unknown as PluginControls}/>));
  expect(state(host,'loading')?.textContent).toContain('Reading installed metadata');
  await act(async () => release({plugins:[]}));
  expect(state(host,'empty')?.textContent).toContain('No installed extension entry points');
  await act(async () => host.querySelector('button')!.click());
  expect(state(host,'error')?.textContent).toContain('Previous catalog retained');
  expect(state(host,'empty')).not.toBeNull();
 } finally { await act(async () => root.unmount()); }
}));

it('maps resource catalog loading, empty and read error to cards', async () => mounted(async host => {
 const root = createRoot(host);
 const controls = {mutate: vi.fn().mockImplementationOnce(async (_id:string,_action:string,body:{operation_id:string}) => ({ok:true,operation_id:body.operation_id,result:{catalog:{server_id:'state-server',resources:[],next_page:null,truncated:false}}})).mockRejectedValueOnce(Error('offline'))} as unknown as ResourceControls;
 try {
  await act(async () => root.render(<MCPResources controls={controls} server={{id:'state-server',name:'State server'}} onClose={()=>{}}/>));
  const read = () => [...document.querySelectorAll('button')].find(button => button.textContent==='Read resource catalog from server')!;
  await act(async () => read().click());
  expect(state(document.body,'empty')?.textContent).toContain('No resources in this catalog');
  await act(async () => read().click());
  expect(state(document.body,'error')?.textContent).toContain('offline');
  expect(state(document.body,'empty')).not.toBeNull();
 } finally { await act(async () => root.unmount()); }
}));
