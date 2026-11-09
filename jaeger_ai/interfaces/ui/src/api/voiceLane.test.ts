import { expect, it, vi } from 'vitest';
import { GatewayClient } from './gateway';
it('marks spoken turns for the existing direct voice lane without changing typed turns or authority',async()=>{
 const client=new GatewayClient();const json=vi.spyOn(client,'json').mockResolvedValue({session_id:'same',request_id:'voice',status:'admitted'});
 await client.send('same','Hello','voice',[],{fast_lane:true});await client.send('same','Typed work','typed',[]);
 expect(json.mock.calls).toEqual([['/v1/sessions/same/turns',{text:'Hello',request_id:'voice',attachment_ids:[],fast_lane:true}],['/v1/sessions/same/turns',{text:'Typed work',request_id:'typed',attachment_ids:[]}]]);
});
