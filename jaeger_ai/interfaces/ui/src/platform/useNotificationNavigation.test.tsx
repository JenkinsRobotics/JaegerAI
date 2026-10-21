import{StrictMode,act}from'react';import{createRoot}from'react-dom/client';import{it,expect,vi}from'vitest';import{useNotificationNavigation}from'./useNotificationNavigation';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it.each([false,true])('peeks after readiness and acknowledges once under StrictMode, initially ready=%s',async(initialReady)=>{
 const id='12345678-1234-4234-9234-123456789012';let pending:unknown={id,destination:{target:'conversation',session_id:'owned-beta-home'}};
 const post=vi.fn(async(type:string,payload?:unknown)=>{if(type==='notifications.navigation')return{navigation:pending};if(type==='notifications.navigationAck'){expect(payload).toEqual({id});pending=null;return{cleared:true};}throw Error('Unexpected execution/permission command');});
 window.jaegerNative={post};const open=vi.fn();function Harness({ready}:{ready:boolean}){useNotificationNavigation(ready,open);return null;}
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 try{
  await act(async()=>root.render(<StrictMode><Harness ready={initialReady}/></StrictMode>));if(!initialReady)expect(post).not.toHaveBeenCalled();
  await act(async()=>root.render(<StrictMode><Harness ready/></StrictMode>));
  expect(open).toHaveBeenCalledExactlyOnceWith({target:'conversation',session_id:'owned-beta-home'});expect(pending).toBeNull();
  await act(async()=>window.dispatchEvent(new CustomEvent('jaeger:native',{detail:{type:'notification.open'}})));
  expect(open).toHaveBeenCalledOnce();
 }finally{await act(async()=>root.unmount());el.remove();delete window.jaegerNative;}
});
