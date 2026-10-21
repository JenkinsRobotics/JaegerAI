import{act}from'react';import{createRoot}from'react-dom/client';import{it,expect,vi}from'vitest';import{LocalComputerPanel}from'./LocalComputerPanel';import type{JaegerSource}from'../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('keeps Gateway inventory and explicit native OS status separate without capture/input/grants',async()=>{
 const source={computers:async()=>({scope:'gateway_process_only',computers:[{id:'gateway-local',kind:'local_gateway',state:'serving',process_id:42,os:'Fixture',architecture:'owned',screen_view:'no_shared_ui_viewport',input_authorization:'per_admitted_turn_and_existing_policy',os_permissions:'not_inferred_from_gateway',recovery:'existing_foreground_lifecycle_owner_only'}],hosted:{state:'not_observed_by_gateway_inventory',allocation_supported:false},requests:{},approvals:{},actions:{allocate:false,restart:false,input:false,capture:false},limits:[]})}as unknown as JaegerSource;
 const post=vi.fn(async(type:string,payload?:unknown)=>{if(type==='computer.status')return{scope:'native_shell_process',process_id:43,screen_os_permission:'granted',input_os_permission:'not_granted_or_undetermined',permission_requested:false,capture_performed:false,input_performed:false};if(type==='computer.settings'){expect(payload).toEqual({target:'accessibility'});return{open_request_accepted:true,permission_changed:false};}throw Error('No tool/capture/input/permission command allowed');});
 const prior=window.jaegerNative;window.jaegerNative={post};const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 try{
  await act(async()=>root.render(<LocalComputerPanel source={source}/>));expect(post).not.toHaveBeenCalled();expect(el.textContent).toContain('process 42');
  await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Read native OS permission status')!.click());expect(el.textContent).toContain('Native process 43');expect(el.textContent).toContain('OS permission is not a tool grant');
  await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Open Accessibility settings')!.click());expect(el.textContent).toContain('did not change any permission');expect(post).toHaveBeenCalledTimes(2);
 }finally{await act(async()=>root.unmount());el.remove();window.jaegerNative=prior;}
});
