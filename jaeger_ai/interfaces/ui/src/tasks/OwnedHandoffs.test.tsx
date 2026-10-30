import {keysWithPrefix} from '../lib/storageKeys';
import {GatewayError} from '../api/gateway';
import {act} from 'react';import {createRoot} from 'react-dom/client';import {beforeEach,expect,it,vi} from 'vitest';
import {OwnedHandoffs} from './OwnedHandoffs';import type {JaegerSource} from '../api/source';
beforeEach(()=>{localStorage.clear();(globalThis as unknown as {IS_REACT_ACT_ENVIRONMENT:boolean}).IS_REACT_ACT_ENVIRONMENT=true;});
const state={handoff_id:'owned-h',outcome:'unknown',cancellation_confirmed:false,child_status:'execution_unknown',child_request_id:'owned-child'};
const row={handoff_id:'owned-h',request_id:'owned-request',task:'Owned task',from_agent_id:'native:origin',to_agent_id:'native:target',current:state};
it('journals an exact leaf Stop, preserves uncertainty across remount, checks without replay',async()=>{
 const stop=vi.fn(async()=>{throw Error('lost acknowledgement');});const original=vi.fn(async(_id,op)=>({handoff_id:'owned-h',request_id:'owned-request',operation_id:op,outcome:'accepted',current:state,unconfirmed_task_ids:['owned-child']}));
 const source={handoffStops:{list:async()=>({handoffs:[row],limit:100}),stop,original}} as unknown as JaegerSource;
 const host=document.createElement('div');document.body.append(host);let root=createRoot(host);await act(async()=>root.render(<OwnedHandoffs source={source}/>));
 await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Stop specialist work')!.click());expect(stop).toHaveBeenCalledTimes(1);const [id,body]=stop.mock.calls[0] as unknown as [string,{operation_id:string;request_id:string}];expect(id).toBe('owned-h');expect(body.request_id).toBe('owned-request');expect(localStorage.getItem('jaeger.ui.handoff-stop.v1.'+body.operation_id)).not.toBeNull();
 await act(async()=>root.unmount());root=createRoot(host);await act(async()=>root.render(<OwnedHandoffs source={source}/>));expect(stop).toHaveBeenCalledTimes(1);
 await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Check original Stop')!.click());expect(original).toHaveBeenCalledWith('owned-h',body.operation_id);expect(stop).toHaveBeenCalledTimes(1);expect(host.textContent).toContain('effect cleanup remains unconfirmed: owned-child');expect(localStorage.getItem('jaeger.ui.handoff-stop.v1.'+body.operation_id)).toBeNull();await act(async()=>root.unmount());host.remove();
});
it('rejects foreign receipt without clearing original intent or claiming stopped',async()=>{
 const intent={id:'owned-h',request_id:'owned-request',operation_id:'owned-op'};localStorage.setItem('jaeger.ui.handoff-stop.v1.owned-op',JSON.stringify(intent));
 const source={handoffStops:{list:async()=>({handoffs:[row],limit:100}),stop:vi.fn(),original:async()=>({handoff_id:'foreign',request_id:'owned-request',operation_id:'owned-op',outcome:'accepted',current:state,unconfirmed_task_ids:[]})}} as unknown as JaegerSource;
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);await act(async()=>root.render(<OwnedHandoffs source={source}/>));await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Check original Stop')!.click());expect(host.textContent).toContain('identity mismatch');expect(localStorage.getItem('jaeger.ui.handoff-stop.v1.owned-op')).not.toBeNull();expect(host.textContent).not.toContain('Cancellation confirmed');await act(async()=>root.unmount());host.remove();
});

it('retains Stop/lease rejection truth without trapping an unadmitted command',async()=>{
 const stop=vi.fn(async()=>{throw new GatewayError('global stop',423);});
 const source={handoffStops:{list:async()=>({handoffs:[row],limit:100}),stop,original:vi.fn()}} as unknown as JaegerSource;
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);await act(async()=>root.render(<OwnedHandoffs source={source}/>));await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Stop specialist work')!.click());expect(stop).toHaveBeenCalledTimes(1);expect(host.textContent).toContain('Stop rejected before execution: global stop');expect(keysWithPrefix('jaeger.ui.handoff-stop.v1.')).toEqual([]);expect(host.textContent).not.toContain('Cancellation confirmed');await act(async()=>root.unmount());host.remove();
});
