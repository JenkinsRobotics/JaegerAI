import {act} from 'react';import {createRoot} from 'react-dom/client';import {it,expect,vi} from 'vitest';import {ChannelDeliveries} from './ChannelDeliveries';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
it('shows pending partial receipts without replay controls, dedupes older pages and retains errors',async()=>{
 const row={id:'owned-effect',run_id:'owned-run',state:'outcome_unknown',claimed_at:'2026-10-20',completed_at:null,delivery_verified:false as const,message_ids:['owned-part']};
 const read=vi.fn().mockResolvedValueOnce({initialized:true,scope:'loaded_entity_effect_ledger_only',deliveries:[row],next_before:20}).mockResolvedValueOnce({initialized:true,scope:'loaded_entity_effect_ledger_only',deliveries:[row,{...row,id:'older',state:'transport_accepted'}],next_before:null}).mockRejectedValueOnce(Error('offline'));
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);const button=(s:string)=>[...host.querySelectorAll('button')].find(b=>b.textContent===s)!;
 try{
  await act(async()=>root.render(<ChannelDeliveries read={read}/>));expect(host.textContent).toContain('Do not resend');expect(host.textContent).toContain('owned-part');
  await act(async()=>button('Load earlier channel receipts').click());expect(read).toHaveBeenNthCalledWith(2,20);expect(host.querySelectorAll('article')).toHaveLength(2);
  await act(async()=>button('Refresh channel receipts').click());expect(host.textContent).toContain('Earlier receipts retained');expect(host.querySelectorAll('article')).toHaveLength(2);
  expect([...host.querySelectorAll('button')].some(b=>/retry|resend|resolve/i.test(b.textContent??''))).toBe(false);
 }finally{await act(async()=>root.unmount());host.remove();}
});
