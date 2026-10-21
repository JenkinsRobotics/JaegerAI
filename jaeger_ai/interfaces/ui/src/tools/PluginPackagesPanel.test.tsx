import {act} from 'react';import {createRoot} from 'react-dom/client';import {expect,it,vi} from 'vitest';
import {PluginPackagesPanel} from './PluginPackagesPanel';import type {JaegerSource,PluginPackages,PackagePlan,InstalledPlugin} from '../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
const plan:PackagePlan={package:'owned-plugin',version:'2.0',installed_version:'1.0',sha256:'b'.repeat(64),attachment_id:'owned-upload',expected_fingerprint:'saved-files',policy_revision:4,entries:[],requires:[],restart_required:true,activation_performed:false,provenance:'fixture wheel metadata'};
const listing={environment:'owned-env',operations:[],supported:'offline wheel',activation_performed:false as const};
async function mount(controls:PluginPackages,source={} as JaegerSource){const element=document.createElement('div');document.body.append(element);const root=createRoot(element);await act(async()=>root.render(<PluginPackagesPanel controls={controls} source={source} sessionId="owned-home" rows={[{package:'owned-plugin'} as InstalledPlugin]} changed={()=>{}}/>));return {element,dispose:async()=>{await act(async()=>root.unmount());element.remove();}};}
async function click(element:HTMLElement,text:string){await act(async()=>[...element.querySelectorAll('button')].find(b=>b.textContent===text)!.click());}
it('stages an explicitly selected wheel, reviews its digest, then sends only the confirmed exact artifact contract',async()=>{
 localStorage.clear();const uploadAttachment=vi.fn(async()=>({attachment_id:'owned-upload',name:'owned_plugin-2.0-py3-none-any.whl',mime:'application/octet-stream',size:4,sha256:plan.sha256!}));
 const change=vi.fn(async(body)=>({ok:true,operation_id:body.operation_id,result:{domain:'plugin_package',package:'owned-plugin',activation_performed:false,state:'installed_disabled'}}));
 const preview=vi.fn(async()=>plan);const view=await mount({list:async()=>listing,preview,change,operation:vi.fn()},{uploadAttachment} as unknown as JaegerSource);
 try{const input=view.element.querySelector('input[type="file"]')!;Object.defineProperty(input,'files',{value:[new File(['data'],'owned_plugin-2.0-py3-none-any.whl')]});await act(async()=>input.dispatchEvent(new Event('change',{bubbles:true})));
 await click(view.element,'Review local wheel');await act(async()=>{await vi.waitFor(()=>expect(preview).toHaveBeenCalled(),{timeout:1000});});expect(change).not.toHaveBeenCalled();expect(uploadAttachment).toHaveBeenCalledWith('owned-home',expect.objectContaining({name:'owned_plugin-2.0-py3-none-any.whl'}),expect.any(String));expect(preview).toHaveBeenCalledWith({action:'install',session_id:'owned-home',attachment_id:'owned-upload'});expect(view.element.textContent).toContain(plan.sha256!);
 await click(view.element,'Confirm package change');expect(change).toHaveBeenCalledWith(expect.objectContaining({action:'install',session_id:'owned-home',attachment_id:'owned-upload',sha256:plan.sha256,expected_fingerprint:'saved-files',expected_policy_revision:4}));expect(view.element.textContent).toContain('No plugin activation or hot unload');
 }finally{await view.dispose();}
});
it('an uncertain command checks original receipt after remount and never replays package installation',async()=>{
 localStorage.clear();const key='jaeger.ui.plugin-package.v1.owned-env';const command={operation_id:'owned-unknown',action:'remove',package:'owned-plugin',expected_fingerprint:'files',expected_policy_revision:4};localStorage.setItem(key,JSON.stringify({command,package:'owned-plugin'}));
 const change=vi.fn(),operation=vi.fn().mockResolvedValueOnce({receipt:null,pending:{error:'Installer outcome unknown'}}).mockResolvedValueOnce({receipt:{ok:false,operation_id:'owned-unknown',error:'Package preflight rejected'}});
 const view=await mount({list:async()=>listing,preview:vi.fn(),change,operation});
 try{await click(view.element,'Check package operation');expect(localStorage.getItem(key)).not.toBeNull();expect(view.element.textContent).toContain('Installer outcome unknown');await click(view.element,'Check package operation');expect(change).not.toHaveBeenCalled();expect(localStorage.getItem(key)).toBeNull();expect(view.element.textContent).toContain('Package preflight rejected');expect(view.element.textContent).not.toContain('Verified package files:');}finally{await view.dispose();}
});
it('unknown upload acknowledgment resolves the original staged file without re-upload or package execution',async()=>{
 localStorage.clear();localStorage.setItem('jaeger.ui.plugin-package.v1.owned-env.upload',JSON.stringify({session_id:'owned-original-home',upload_key:'owned-upload-key'}));
 const uploadAttachment=vi.fn(),change=vi.fn(),preview=vi.fn(async()=>plan);const view=await mount({list:async()=>listing,preview,change,operation:vi.fn()},{uploadAttachment} as unknown as JaegerSource);
 try{await click(view.element,'Check uploaded wheel');expect(preview).toHaveBeenCalledWith({action:'install',session_id:'owned-original-home',upload_key:'owned-upload-key'});expect(uploadAttachment).not.toHaveBeenCalled();expect(change).not.toHaveBeenCalled();}finally{await view.dispose();}
});
it('explicit backup compensation gets a new command and preserves the original unknown journal',async()=>{
 localStorage.clear();const key='jaeger.ui.plugin-package.v1.owned-env';const original={command:{operation_id:'owned-unknown-update',action:'install',session_id:'owned-home',attachment_id:'owned-upload',sha256:'b'.repeat(64),expected_fingerprint:'files',expected_policy_revision:4},package:'owned-plugin'};localStorage.setItem(key,JSON.stringify(original));
 const history={...listing,operations:[{operation_id:'owned-unknown-update',package:'owned-plugin',version:'2.0',action:'install',phase:'installer_started',backup_available:true}]};
 const change=vi.fn(async(body)=>({ok:true,operation_id:body.operation_id,result:{domain:'plugin_package',package:'owned-plugin',activation_performed:false,state:'installed_disabled'}}));
 const preview=vi.fn(async()=>({...plan,version:'1.0',installed_version:'2.0'}));const view=await mount({list:async()=>history,preview,change,operation:vi.fn()});
 try{await click(view.element,'Review preserved revision of owned-plugin');expect(change).not.toHaveBeenCalled();await click(view.element,'Confirm package change');expect(change).toHaveBeenCalledOnce();expect(change.mock.calls[0][0]).toMatchObject({action:'restore',restore_from:'owned-unknown-update'});expect(change.mock.calls[0][0].operation_id).not.toBe('owned-unknown-update');expect(JSON.parse(localStorage.getItem(key+'.unknown.owned-unknown-update')!)).toEqual(original);expect(localStorage.getItem(key)).toBeNull();}finally{await view.dispose();}
});
