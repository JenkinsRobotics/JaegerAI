import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect,it,vi} from 'vitest';
import {MCPSetup} from './MCPSetup';
import {MCPToolRestrictions} from './MCPToolRestrictions';
import type {MCPConfiguration,MCPConfigurationIntent} from '../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('reviews exact tool restrictions then exposes receipt-bound restore without live-connect claim',async()=>{
 localStorage.clear();const policy={include:[],exclude:[],gated:true};let revision='r1',restore:string|undefined;
 const controls:MCPConfiguration={read:vi.fn(async()=>({config_revision:revision,restore_operation:restore,servers:[{name:'owned',startup_enabled:false,transport:'stdio',status:'not_probed' as const,tool_policy:policy}]})),change:vi.fn(async(body:MCPConfigurationIntent)=>{revision='r2';restore=body.action==='policy'?body.operation_id:undefined;return {operation_id:body.operation_id,outcome:'saved' as const,config_revision:revision,connection_attempted:false as const};}),operation:vi.fn()};
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 const click=async(text:string)=>act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent===text)!.click());
 try{
  await act(async()=>root.render(<MCPSetup controls={controls}/>));await click('Edit next-startup tool restrictions for owned');
  const input=host.querySelector<HTMLTextAreaElement>('[aria-label="Exclude tools for owned"]')!;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(input,'["write_one"]');input.dispatchEvent(new Event('input',{bubbles:true}));});
  await click('Review tool restrictions for owned');expect(controls.change).not.toHaveBeenCalled();expect(host.textContent).toContain('Current registered tools and in-flight work are unchanged');
  await click('Confirm configuration');expect(controls.change).toHaveBeenCalledExactlyOnceWith({operation_id:expect.any(String),action:'policy',name:'owned',expected_revision:'r1',policy:{include:[],exclude:['write_one'],gated:true}});
  const original=restore;await click('Review restore previous tool filter');expect(controls.change).toHaveBeenCalledTimes(1);await click('Confirm configuration');
  expect(controls.change).toHaveBeenLastCalledWith({operation_id:expect.any(String),action:'restore_policy',restore_from:original,expected_revision:'r2'});
 }finally{await act(async()=>root.unmount());host.remove();localStorage.clear();}
});
it('retains an edited policy draft and original revision across a newer inventory',async()=>{
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);const onReview=vi.fn();const policy={include:[],exclude:[],gated:false};
 const click=async(text:string)=>act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent===text)!.click());
 try{
  await act(async()=>root.render(<MCPToolRestrictions name="owned" revision="old" policy={policy} disabled={false} onReview={onReview}/>));await click('Edit next-startup tool restrictions for owned');
  const field=host.querySelector<HTMLTextAreaElement>('[aria-label="Exclude tools for owned"]')!;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,'["draft_tool"]');field.dispatchEvent(new Event('input',{bubbles:true}));});
  await act(async()=>root.render(<MCPToolRestrictions name="owned" revision="new" policy={{...policy,exclude:['new_rule']}} disabled={false} onReview={onReview}/>));
  expect(field.value).toBe('["draft_tool"]');expect(host.textContent).toContain('Draft retained');expect([...host.querySelectorAll('button')].find(b=>b.textContent==='Review tool restrictions for owned')?.disabled).toBe(true);expect(onReview).not.toHaveBeenCalled();
 }finally{await act(async()=>root.unmount());host.remove();}
});
