import { act } from 'react'; import { createRoot } from 'react-dom/client'; import { it, expect, vi } from 'vitest';
import { SpecialistConfiguration } from './SpecialistConfiguration'; import type { SpecialistControls } from '../api/source';
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
it('preserves stale prompt draft and its revision; reload reconciles without replaying a failed save', async () => {
  const draft = { specialty: 'Owned specialty', summary: 'Owned draft', instructions: 'Preserve my instructions' };
  const key = 'jaeger.ui.specialist-settings.v1.native%3Aowned'; localStorage.setItem(key, JSON.stringify({ draft, baseRevision: 0 }));
  const read = vi.fn(async () => ({ agent_id: 'native:owned', revision: 1, editable: true, specialty: 'Server specialty', summary: 'Other edit', instructions: 'Saved instructions' }));
  const save = vi.fn(async () => { throw Error('revision conflict'); }); const controls = { read, save, templates: vi.fn() } as unknown as SpecialistControls;
  const element = document.createElement('div'); document.body.append(element); let root = createRoot(element);
  const render = () => <SpecialistConfiguration agentId="native:owned" controls={controls} onClose={vi.fn()} onSaved={vi.fn()} />;
  const button = (label: string) => [...document.querySelectorAll('button')].find(b => b.textContent === label)!;
  await act(async () => root.render(render()));
  expect(document.querySelector<HTMLTextAreaElement>('[aria-label="Specialist instructions"]')?.value).toBe(draft.instructions);
  await act(async () => button('Save specialist settings').click());
  expect(save).toHaveBeenCalledExactlyOnceWith('native:owned', { expected_revision: 0, settings: draft });
  await act(async () => root.unmount()); root = createRoot(element); await act(async () => root.render(render()));
  expect(button('Save specialist settings').disabled).toBe(true);
  await act(async () => button('Check uncertain settings save').click());
  expect(save).toHaveBeenCalledOnce(); expect(document.body.textContent).toContain('Your draft is preserved');
  expect(document.querySelector<HTMLTextAreaElement>('[aria-label="Specialist instructions"]')?.value).toBe(draft.instructions);
  expect(localStorage.getItem(key)).toContain(draft.instructions);
  await act(async () => root.unmount()); element.remove(); localStorage.removeItem(key);
});
it('requests the saved revision export and refuses a mismatched receipt without touching drafts',async()=>{
 const draft={specialty:'draft',summary:'draft',instructions:'Unsent local draft'};const key='jaeger.ui.specialist-settings.v1.native%3Aowned';localStorage.setItem(key,JSON.stringify({draft,baseRevision:0}));
 const exportTemplate=vi.fn(async()=>({agent_id:'native:other',revision:1,content:'{}',sha256:'invalid',filename:'untrusted',visibility:'owner_local' as const,export_policy:'prompt_only_no_grants' as const}));
 const save=vi.fn();const controls:SpecialistControls={templates:vi.fn(),read:vi.fn(async()=>({agent_id:'native:owned',revision:1,editable:true,specialty:'saved',summary:'saved',instructions:'Saved prompt'})),save,exportTemplate};
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 try{
  await act(async()=>root.render(<SpecialistConfiguration agentId="native:owned" controls={controls} onClose={()=>{}} onSaved={()=>{}}/>));
  await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Export current saved prompt template')!.click());
  expect(exportTemplate).toHaveBeenCalledExactlyOnceWith('native:owned',1);expect(save).not.toHaveBeenCalled();
  expect(document.body.textContent).toContain('Template export failed');expect(document.body.textContent).not.toContain('download requested');expect(localStorage.getItem(key)).toContain('Unsent local draft');
 }finally{await act(async()=>root.unmount());host.remove();localStorage.removeItem(key);}
});
