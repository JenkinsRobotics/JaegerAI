import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect,it,vi} from 'vitest';
import {ChannelDeliveries} from './ChannelDeliveries';
import type {ChannelDeliveries as Snapshot} from '../api/source';

(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;

it('maps loading, empty, and error receipts to WidgetCard states',async()=>{
 let resolve!: (value:Snapshot)=>void;
 const read=vi.fn().mockImplementationOnce(()=>new Promise(r=>{resolve=r;}))
   .mockRejectedValueOnce(Error('offline'));
 const host=document.createElement('div'),root=createRoot(host);
 const state=(value:string)=>host.querySelector(`[data-state="${value}"]`);
 try{
  await act(async()=>root.render(<ChannelDeliveries read={read}/>));
  expect(state('loading')?.textContent).toContain('Loading channel receipts');
  await act(async()=>resolve({initialized:true,scope:'loaded_entity_effect_ledger_only',deliveries:[],next_before:null}));
  expect(state('empty')?.textContent).toContain('No retained send_message effects');
  await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Refresh channel receipts')!.click());
  expect(state('error')?.textContent).toContain('Earlier receipts retained');
  expect(state('empty')).not.toBeNull();
 }finally{await act(async()=>root.unmount());}
});
