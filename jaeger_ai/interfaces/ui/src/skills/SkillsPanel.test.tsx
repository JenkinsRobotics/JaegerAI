import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { SkillsPanel } from './SkillsPanel';
import type { JaegerSource, SkillDetail } from '../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('inspects exact skill metadata and rejects a mismatched identity', async()=>{
  const metadata={name:'owned',category:'fixture',description:'Local skill',origin:'user',lifecycle:'explicit',skill_class:'first-class',platforms:[],requires_tools:['owned-read'],optional_tools:[],requires_toolsets:[],requires_plugins:[],aliases:[],tags:[],auto_activate:false,tier:'standard',availability:'not_probed',origin_verified:false,execution_authorized:false,scope:'discovered_registry_metadata'} as SkillDetail;
  const detail=vi.fn(async()=>metadata),source={skills:async()=>({skills:[metadata],count:1}),skillDetail:detail} as unknown as JaegerSource;
  const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
  try{
    await act(async()=>{root.render(<SkillsPanel source={source}/>);});
    await act(async()=>{await new Promise(resolve=>setTimeout(resolve,180));});
    const inspect=[...host.querySelectorAll('button')].find(b=>b.textContent==='Inspect owned')!;
    await act(async()=>inspect.click());
    expect(detail).toHaveBeenCalledExactlyOnceWith('owned','fixture');
    expect(host.textContent).toContain('Required tools: owned-read');
    expect(host.textContent).toContain('not verified publisher identity');
    detail.mockResolvedValueOnce({...metadata,name:'other'});
    await act(async()=>inspect.click());
    expect(host.textContent).toContain('Skill identity mismatch');
    expect(host.querySelector('[aria-label="Skill metadata"]')).toBeNull();
  } finally {await act(async()=>root.unmount());host.remove();}
});
