import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { it, expect, vi } from 'vitest';
import { NewChatMenu } from './NewChatMenu';
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
it('recovers an acknowledged creation by saved command without submitting another creation', async () => {
  const key = 'jaeger.ui.agent-create.v1';
  localStorage.setItem(key, JSON.stringify({ operationId: 'owned-create', name: 'Owned bot', job: 'Fixture role' }));
  const create = vi.fn(), recover = vi.fn(async () => ({ failed: undefined }));
  const element = document.createElement('div'); document.body.append(element);
  const root = createRoot(element);
  await act(async () => root.render(<NewChatMenu anchor={null} agents={[]} onClose={() => {}} onNewChat={() => {}} onCreateAgent={create} onRecoverAgent={recover} />));
  const check = [...document.querySelectorAll('button')].find(b => b.textContent === 'Check saved creation')!;
  expect(check).toBeTruthy();
  expect([...document.querySelectorAll('button')].find(b => b.textContent === 'Create')?.disabled).toBe(true);
  await act(async () => check.click());
  expect(recover).toHaveBeenCalledExactlyOnceWith('owned-create'); expect(create).not.toHaveBeenCalled();
  expect(localStorage.getItem(key)).toBeNull();
  await act(async () => root.unmount()); element.remove();
});
it('dispatches one explicit local snapshot creation and preserves uncertain intent for lookup',async()=>{
 localStorage.clear();const anchor=document.createElement('button');document.body.append(anchor);
 const content=JSON.stringify({format:'jaeger.specialist-template',schema_version:1});
 const create=vi.fn(async()=>{throw Error('lost ACK');}),recover=vi.fn();
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 try{
  await act(async()=>root.render(<NewChatMenu anchor={anchor} agents={[]} onClose={()=>{}} onNewChat={()=>{}} onCreateAgent={create} onRecoverAgent={recover}/>));
  await act(async()=>[...document.querySelectorAll('[role="menuitem"]')].find(b=>b.textContent?.includes('Create agent'))!.dispatchEvent(new MouseEvent('click',{bubbles:true})));
  const input=document.querySelector<HTMLInputElement>('input[placeholder="Research"]')!,field=document.querySelector<HTMLTextAreaElement>('[aria-label="Local prompt template JSON"]')!;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'Owned copy');input.dispatchEvent(new Event('input',{bubbles:true}));Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,content);field.dispatchEvent(new Event('input',{bubbles:true}));});
  await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Create')!.click());
  const saved=JSON.parse(localStorage.getItem('jaeger.ui.agent-create.v1')!);
  expect(saved.snapshot).toBe(content);expect(create).toHaveBeenCalledExactlyOnceWith('Owned copy','',saved.operationId,undefined,content);
  expect([...document.querySelectorAll('button')].find(b=>b.textContent==='Create')?.disabled).toBe(true);
 }finally{await act(async()=>root.unmount());host.remove();anchor.remove();localStorage.clear();}
});
it('selects distinct saved versions with the same catalog identity',async()=>{
 localStorage.clear();const anchor=document.createElement('button');document.body.append(anchor);const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 const template={id:'saved:native:source',name:'Owned saved template',specialty:'owned',summary:'owned',instructions:'owned',tools_granted:false as const};
 const controls={templates:vi.fn(async()=>({templates:[{...template,version:1},{...template,version:2}]})),read:vi.fn(),save:vi.fn()};const create=vi.fn(async()=>{throw Error('Lost ACK');});
 try{
  await act(async()=>root.render(<NewChatMenu anchor={anchor} agents={[]} controls={controls} onClose={()=>{}} onNewChat={()=>{}} onCreateAgent={create}/>));
  await act(async()=>[...document.querySelectorAll('[role="menuitem"]')].find(b=>b.textContent?.includes('Create agent'))!.dispatchEvent(new MouseEvent('click',{bubbles:true})));
  const select=document.querySelector<HTMLSelectElement>('[aria-label="Agent template"]')!;
  expect([...select.options].map(o=>o.value)).toEqual(['','saved:native:source:v1','saved:native:source:v2']);
  const input=document.querySelector<HTMLInputElement>('input[placeholder="Research"]')!;
  await act(async()=>{select.value='saved:native:source:v2';select.dispatchEvent(new Event('change',{bubbles:true}));Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'Owned version two');input.dispatchEvent(new Event('input',{bubbles:true}));});
  await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Create')!.click());
  expect(create).toHaveBeenCalledExactlyOnceWith('Owned version two','',expect.any(String),{id:'saved:native:source',version:2},undefined);
  expect(JSON.parse(localStorage.getItem('jaeger.ui.agent-create.v1')!).template).toEqual({id:'saved:native:source',version:2});
 }finally{await act(async()=>root.unmount());host.remove();anchor.remove();localStorage.clear();}
});
