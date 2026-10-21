import {act} from 'react';import {createRoot} from 'react-dom/client';import {expect,it,vi} from 'vitest';
import {NativeNotifications} from './NativeNotifications';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
async function mount(post:NonNullable<Window['jaegerNative']>['post'],run:(host:HTMLDivElement)=>Promise<void>){const previous=window.jaegerNative;window.jaegerNative={post};const host=document.createElement('div');document.body.append(host);const root=createRoot(host);try{await act(async()=>root.render(<NativeNotifications/>));await run(host);}finally{await act(async()=>root.unmount());host.remove();window.jaegerNative=previous;}}
it('reads denied permission without requesting permission or sending a notification',async()=>{
 const post=vi.fn(async()=>({authorization:'denied',permission_requested:false}));
 await mount(post,async host=>{expect(post).toHaveBeenCalledExactlyOnceWith('notifications.status');expect((Array.from(host.querySelectorAll('button')).find(b=>b.textContent==='Send local notification check')! as HTMLButtonElement).disabled).toBe(true);});
});
it('reports only OS submission acceptance and never retries an uncertain submission',async()=>{
 const post=vi.fn().mockResolvedValueOnce({authorization:'authorized',permission_requested:false}).mockRejectedValueOnce(Error('lost submission reply'));
 await mount(post,async host=>{await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Send local notification check')!.click());expect(post).toHaveBeenCalledTimes(2);expect(host.textContent).toContain('submission may be unknown');expect(host.textContent).not.toContain('macOS accepted');});
});
