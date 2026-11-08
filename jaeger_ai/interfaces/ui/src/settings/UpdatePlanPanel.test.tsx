import{act}from'react';import{createRoot}from'react-dom/client';import{it,expect,vi}from'vitest';import{UpdatePlanPanel}from'./UpdatePlanPanel';import type{JaegerSource,UpdatePlan}from'../api/source';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('channel changes request a real local plan and never expose an enabled apply/restart action',async()=>{
 const updatePlan=vi.fn(async(channel:'stable'|'latest')=>({component:'jaeger-update-plan',channel,reported_package_version:'0.13.0',install_method:'dev-checkout',source_checkout_revision:'owned',source_checkout_dirty:true,identity_scope:'checkout_only',migration_state:'unknown',active_instance_schema:null,installed_schema:'0.5.0',work:{active_requests:0,unknown_requests:1,nonterminal_tasks:0},restart_blockers:['execution_unknown_requires_reconciliation'],restart_policy:'manual_no_service_action',release_state:'not_probed',signature_state:'no_verified_candidate',automatic_install_supported:false,automatic_restart_supported:false,check_command:['jaeger','update','--check','--channel',channel],manual_update_command:['jaeger','update','--channel',channel],rollback:{available:false,command:['jaeger','update','--rollback']},limits:['No install or restart executed']} as UpdatePlan));
 const source={updatePlan}as unknown as JaegerSource;localStorage.removeItem('jaeger.ui.update-review-channel.v1');const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 try{
  await act(async()=>root.render(<UpdatePlanPanel source={source}/>));expect(el.textContent).toContain('not_probed');expect(el.textContent).toContain('execution unknown requires reconciliation');
  await act(async()=>{const select=el.querySelector('select')!;select.value='latest';select.dispatchEvent(new Event('change',{bubbles:true}));});expect(updatePlan).toHaveBeenLastCalledWith('latest');
  expect(el.textContent).toContain('jaeger update --check --channel latest');expect(el.querySelectorAll('button')).toHaveLength(1);expect(el.textContent).toContain('not executed here');
 }finally{await act(async()=>root.unmount());el.remove();localStorage.removeItem('jaeger.ui.update-review-channel.v1');}
});

it('warns when the native shell or Gateway startup revision differs from checkout',async()=>{
 window.jaegerNative={post:async()=>({version:'0.13.0',build:'0.13.0+11111111',dev_build:true})};
 const source={updatePlan:async()=>({component:'jaeger-update-plan',channel:'stable',reported_package_version:'0.13.0',install_method:'product-checkout',source_checkout_revision:'2'.repeat(40),runtime_source_revision:'3'.repeat(40),source_checkout_dirty:false,identity_scope:'checkout_only',migration_state:'current',active_instance_schema:'0.5.0',installed_schema:'0.5.0',work:{active_requests:0,unknown_requests:0,nonterminal_tasks:0},restart_blockers:[],restart_policy:'manual',release_state:'not_probed',signature_state:'not_probed',check_command:[],manual_update_command:[],rollback:{available:true,command:[]},limits:[]})}as unknown as JaegerSource;
 localStorage.removeItem('jaeger.ui.update-review-channel.v1');const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 try{
  await act(async()=>root.render(<UpdatePlanPanel source={source}/>));
  expect(el.querySelector('[role="alert"]')?.textContent).toContain('different revisions');
  expect(el.textContent).toContain('Gateway startup revision '+ '3'.repeat(40));
 }finally{await act(async()=>root.unmount());el.remove();delete window.jaegerNative;}
});
