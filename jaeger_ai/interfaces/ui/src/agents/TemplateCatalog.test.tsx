import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect,it,vi} from 'vitest';
import {TemplateCatalog} from './TemplateCatalog';
import type {TemplateCatalogControls} from '../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('reviews saved source revision then recovers original catalog result across reopen without replay',async()=>{
 localStorage.clear();const state={agent_id:'native:owned',source_revision:2,catalog_revision:1,hidden:false,versions:[{version:1,sha256:'owned'}]};
 const controls:TemplateCatalogControls={read:vi.fn(async()=>state),change:vi.fn(async()=>{throw Error('Lost ACK');}),operation:vi.fn(async id=>({operation_id:id,outcome:'saved' as const,result:{...state,catalog_revision:2,versions:[...state.versions,{version:3,sha256:'new'}]}}))};
 const host=document.createElement('div');document.body.append(host);let root=createRoot(host);
 const render=()=> <TemplateCatalog agentId="native:owned" controls={controls}/>;
 const click=async(text:string)=>act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent===text)!.click());
 try{
  await act(async()=>root.render(render()));await click('Review save current prompt as template');expect(controls.change).not.toHaveBeenCalled();
  await click('Confirm local template change');const id=localStorage.getItem('jaeger.ui.template.catalog.v1.native%3Aowned')!;
  expect(controls.change).toHaveBeenCalledExactlyOnceWith('native:owned',{operation_id:id,action:'save',expected_revision:2,expected_catalog_revision:1});
  await act(async()=>root.unmount());root=createRoot(host);await act(async()=>root.render(render()));
  await click('Inspect original template result');expect(controls.operation).toHaveBeenCalledExactlyOnceWith(id);expect(controls.change).toHaveBeenCalledTimes(1);
  expect(host.textContent).toContain('Version 3');expect(localStorage.getItem('jaeger.ui.template.catalog.v1.native%3Aowned')).toBeNull();
 }finally{await act(async()=>root.unmount());host.remove();localStorage.clear();}
});
