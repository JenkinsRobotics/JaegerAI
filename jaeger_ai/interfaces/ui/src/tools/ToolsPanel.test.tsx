import { act } from 'react'; import { createRoot } from 'react-dom/client'; import { it, expect, vi } from 'vitest';
import { ToolsPanel } from './ToolsPanel'; import type { JaegerSource } from '../api/source';
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
it('retains last inventory on transport failure and never equates registration with availability', async () => {
  const tools = vi.fn().mockResolvedValueOnce({tools:[{name:'owned-read',description:'Reads fixture data',source:'gateway',toolset:'files',side_effect:'read',permission_tier:'scoped'}],count:1,servers:[],mcp_initialized:false,execution_authorized:false}).mockRejectedValueOnce(Error('offline'));
  const element = document.createElement('div'); document.body.append(element); const root = createRoot(element);
  await act(async () => { root.render(<ToolsPanel source={{tools} as unknown as JaegerSource} />); });
  await act(async () => { await new Promise(r => setTimeout(r, 180)); });
  expect(element.textContent).toContain('owned-read'); expect(element.textContent).toContain('Availability not probed');
  await act(async () => { [...element.querySelectorAll('button')].find(b=>b.textContent==='Refresh registered inventory')!.click(); });
  await act(async () => { await new Promise(r => setTimeout(r, 180)); });
  expect(element.textContent).toContain('Previous inventory retained'); expect(element.textContent).toContain('owned-read'); expect(tools).toHaveBeenCalledTimes(2);
  await act(async () => root.unmount()); element.remove();
});
