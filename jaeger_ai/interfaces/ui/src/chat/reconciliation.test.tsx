import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {beforeEach,expect,it,vi} from 'vitest';
import {normalizeFrame} from '../api/gateway';
import {parseSSEChunk} from '../api/sse';
import {followTurn} from './followTurn';
import {requestOutcome} from './requestOutcome';
import {WebHost} from './webHost';
import {MinimalChat} from './MinimalChat';
import type {GatewayEvent} from '../api/types';
import type {JaegerSource} from '../api/source';
import {applyPart,type ChatPart} from './host';
// Captured from isolated GatewaySessionStore.complete_request reconciliation receipts.
const receipts: Record<string, {status:string;result:Record<string,unknown>;event:Record<string,unknown>}> = {
  "completed": {
    "status": "completed",
    "result": {
      "output": "",
      "status": "completed",
      "backend": "native_receipt",
      "turn_id": "58c570e3d87c4f3aaffad82d76f6071b",
      "reconciliation": {
        "status": "completed",
        "reply": {
          "text": ""
        }
      }
    },
    "event": {
      "event_id": 4,
      "session_id": "audit-completed",
      "event": "turn.reconciled",
      "data": {
        "output": "",
        "status": "completed",
        "backend": "native_receipt",
        "turn_id": "58c570e3d87c4f3aaffad82d76f6071b",
        "reconciliation": {
          "status": "completed",
          "reply": {
            "text": ""
          }
        },
        "request_id": "r-completed"
      },
      "timestamp": 1794147975.3737106
    }
  },
  "failed": {
    "status": "failed",
    "result": {
      "output": "",
      "status": "failed",
      "backend": "native_receipt",
      "turn_id": "669b6a83331445bebc70341b3613db73",
      "reconciliation": {
        "status": "failed",
        "reply": {
          "text": ""
        }
      }
    },
    "event": {
      "event_id": 8,
      "session_id": "audit-failed",
      "event": "turn.reconciled",
      "data": {
        "output": "",
        "status": "failed",
        "backend": "native_receipt",
        "turn_id": "669b6a83331445bebc70341b3613db73",
        "reconciliation": {
          "status": "failed",
          "reply": {
            "text": ""
          }
        },
        "request_id": "r-failed"
      },
      "timestamp": 1794147975.3801882
    }
  },
  "cancelled": {
    "status": "cancelled",
    "result": {
      "output": "",
      "status": "cancelled",
      "backend": "native_receipt",
      "turn_id": "e0267c27ae0f44d6a9b12aeead855b78",
      "reconciliation": {
        "status": "cancelled",
        "reply": {
          "text": ""
        }
      }
    },
    "event": {
      "event_id": 12,
      "session_id": "audit-cancelled",
      "event": "turn.reconciled",
      "data": {
        "output": "",
        "status": "cancelled",
        "backend": "native_receipt",
        "turn_id": "e0267c27ae0f44d6a9b12aeead855b78",
        "reconciliation": {
          "status": "cancelled",
          "reply": {
            "text": ""
          }
        },
        "request_id": "r-cancelled"
      },
      "timestamp": 1794147975.3876846
    }
  }
};
function event(status:string):GatewayEvent {
 const row=receipts[status].event;
 const wire=`id: ${row.event_id}\nevent: ${row.event}\ndata: ${JSON.stringify(row)}\n\n`;
 return normalizeFrame(parseSSEChunk(wire).frames[0]);
}
vi.mock('./reveal',()=>({useRevealedText:(text:string)=>text}));
beforeEach(()=>localStorage.clear());

it.each(['completed','failed','cancelled'])('real stored %s receipt survives SSE normalization',status=>{
 expect(event(status)).toMatchObject({event:'turn.reconciled',request_id:'r-'+status,payload:{status,backend:'native_receipt'}});
});
it.each(['completed','failed','cancelled'])('durable lookup control preserves %s',status=>{
 expect(requestOutcome(receipts[status],()=>{})).toBe(status==='completed'?'complete':status);
});
it.each(['failed','cancelled'])('followed reconciled %s is not success',async status=>{
 const ev=event(status);const parts:ChatPart[]=[];
 const result=await followTurn({source:{stream:async(_s,_c,emit)=>emit(ev)},sessionId:ev.session_id!,requestId:ev.request_id!,turnId:typeof ev.turn_id==='string'?ev.turn_id:undefined,cursor:0,signal:new AbortController().signal,onPart:p=>parts.push(p),backoffMs:[]});
 expect(result.state).toBe(status);
});
it('old reconciled failure cannot settle newer active request, including after reconnect',async()=>{
 const old=event('failed');const parts:ChatPart[]=[];const cursors:number[]=[];let n=0;
 const result=await followTurn({source:{stream:async(_s,c,emit)=>{
 cursors.push(c!);if(n++===0){emit({...old,event_id:20});emit({event:'turn.delta',event_id:21,request_id:'new',payload:{delta:'New work'}});throw Error('Owned disconnect');}
 emit({...old,event_id:20});emit({...old,event_id:22});emit({event:'turn.failed',event_id:23,request_id:'new',payload:{error:'New failure'}});
 }},sessionId:old.session_id!,requestId:'new',cursor:19,signal:new AbortController().signal,onPart:p=>parts.push(p),backoffMs:[0],sleep:async()=>{}});
 expect(result.state).toBe('failed');expect(cursors).toEqual([19,21]);expect(parts).toEqual([{kind:'markdownContent',text:'New work'},{kind:'error',message:'New failure'}]);
});
it('duplicate reconciled event for followed request at cursor is ignored',async()=>{
 const ev=event('failed');const result=await followTurn({source:{stream:async(_s,_c,emit)=>{emit({...ev,event_id:20});emit({...ev,event:'turn.cancelled',event_id:21});}},sessionId:ev.session_id!,requestId:ev.request_id!,cursor:20,signal:new AbortController().signal,onPart:()=>{},backoffMs:[]});expect(result.state).toBe('cancelled');
});
it('reconnect preserves failed reconciliation status',async()=>{
 const ev=event('failed');let n=0;
 const result=await followTurn({source:{stream:async(_s,_c,emit)=>{if(n++===0)throw Error('Owned disconnect');emit(ev);}},sessionId:ev.session_id!,requestId:ev.request_id!,cursor:0,signal:new AbortController().signal,onPart:()=>{},backoffMs:[0],sleep:async()=>{}});expect(result.state).toBe('failed');
});

async function renderReceipt(kind:'reconciled'|'normal') {
 const ev=event('failed');let emit!:(e:GatewayEvent)=>void;
 const source={kind:'live',send:vi.fn(),agents:async()=>[],session:async()=>({session_id:ev.session_id,messages:[{role:'user',request_id:ev.request_id,content:'Owned saved request'}]}),sessionControl:async()=>({latest_request:{request_id:ev.request_id,status:'running'}}),requestStatus:async()=>({session_id:ev.session_id,request_id:ev.request_id,turn_id:ev.turn_id,status:'running',input_text:'Owned saved request'}),stream:async(_s:string,_c:number,cb:typeof emit,signal:AbortSignal)=>{emit=cb;await new Promise<void>(resolve=>signal.addEventListener('abort',()=>resolve(),{once:true}));}} as unknown as JaegerSource;
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 try {
 await act(async()=>root.render(<MinimalChat host={new WebHost(source)} sessionId={ev.session_id!}/>));
 await vi.waitFor(()=>expect(emit).toBeTypeOf('function'));
 expect(el.querySelector('[aria-label^="Stop"]')).not.toBeNull();
 await act(async()=>emit({event:'turn.delta',event_id:Number(ev.event_id)-1,request_id:ev.request_id,payload:{delta:'Visible partial before failure'}}));
 await act(async()=>emit(kind==='normal'?{...ev,event:'turn.failed',payload:{...ev.payload,error:'Request failed'}}:ev));
 expect(el.querySelector('[aria-label^="Stop"]')).toBeNull();
 expect(source.send).not.toHaveBeenCalled();
 expect(el.textContent).toContain('Visible partial before failure');
 return el.textContent;
 }finally{act(()=>root.unmount());el.remove();}
}
it('normal failure visibly displays error control',async()=>expect(await renderReceipt('normal')).toContain('Request failed'));
it('reconciled failure visibly displays error',async()=>expect(await renderReceipt('reconciled')).toContain('Request failed'));

it.each(['completed','failed','cancelled'])('preserves partial output and authoritative %s status',async status=>{
 const ev=event(status);ev.payload={...ev.payload,output:'Partial result',error:'Native execution failed'};
 const parts:ChatPart[]=[];
 const result=await followTurn({source:{stream:async(_s,_c,emit)=>emit(ev)},sessionId:ev.session_id!,requestId:ev.request_id!,cursor:0,signal:new AbortController().signal,onPart:p=>parts.push(p),backoffMs:[]});
 expect(result.state).toBe(status==='completed'?'complete':status);
 expect(parts).toContainEqual({kind:'markdownContent',text:'Partial result',role:'final',itemId:'final'});
 expect(parts.filter(p=>p.kind==='error')).toEqual(status==='failed'?[{kind:'error',message:'Native execution failed'}]:[]);
});
it.each([undefined,null,'','running','queued','unexpected','execution_unknown'])('unsettled reconciliation status %s cannot become success',async status=>{
 const ev=event('failed');ev.payload={...ev.payload,status,output:'Observed partial text'};
 const parts:ChatPart[]=[];
 const result=await followTurn({source:{stream:async(_s,_c,emit)=>emit(ev)},sessionId:ev.session_id!,requestId:ev.request_id!,cursor:0,signal:new AbortController().signal,onPart:p=>parts.push(p),backoffMs:[]});
 expect(result.state).toBe('unknown');expect(parts).toContainEqual({kind:'markdownContent',text:'Observed partial text',role:'final',itemId:'final'});
 expect(parts).toContainEqual({kind:'warning',message:'Execution outcome is unknown. This request has been preserved; it will not be resent.'});
});

it.each(['failed','cancelled'])('retains previously streamed partial text when reconciled %s has empty output',async status=>{
 const ev=event(status);let parts:ChatPart[]=[];
 const result=await followTurn({source:{stream:async(_s,_c,emit)=>{
 emit({event:'turn.delta',event_id:0,request_id:ev.request_id,payload:{delta:'Observed before interruption'}});
 emit(ev);
 }},sessionId:ev.session_id!,requestId:ev.request_id!,cursor:-1,signal:new AbortController().signal,onPart:p=>{parts=applyPart(parts,p);},backoffMs:[]});
 expect(result.state).toBe(status);
 expect(parts.filter(p=>p.kind==='markdownContent').map(p=>p.text)).toEqual(['Observed before interruption']);
 expect(parts.filter(p=>p.kind==='error')).toEqual(status==='failed'?[{kind:'error',message:'Request failed'}]:[]);
});
it.each(['failed','cancelled','execution_unknown'])('durable %s empty receipt also preserves observed partial text',status=>{
 let parts:ChatPart[]=[{kind:'markdownContent',text:'Observed partial'}];
 requestOutcome({status,result:{output:''}},p=>{parts=applyPart(parts,p);});
 expect(parts.filter(p=>p.kind==='markdownContent').map(p=>p.text)).toEqual(['Observed partial']);
});

it.each(['completed','failed','cancelled'])('status fallback preserves %s empty-output semantics',async status=>{
 const ev=event(status);let parts:ChatPart[]=[];
 const result=await followTurn({source:{stream:async(_s,_c,emit)=>emit({event:'turn.delta',event_id:1,request_id:ev.request_id,payload:{delta:'Provisional text'}}),requestStatus:async()=>({session_id:ev.session_id!,request_id:ev.request_id!,status,result:{output:''}})},sessionId:ev.session_id!,requestId:ev.request_id!,cursor:0,signal:new AbortController().signal,onPart:p=>{parts=applyPart(parts,p);},backoffMs:[]});
 expect(result.state).toBe(status==='completed'?'complete':status);
 expect(parts.filter(p=>p.kind==='markdownContent').map(p=>p.text)).toEqual(status==='completed'?['']:['Provisional text']);
});
