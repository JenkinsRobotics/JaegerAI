import {expect,it} from 'vitest';
import {mapEvent} from './eventMap';
import {applyPart,type ChatPart} from './host';
import {activityPhrase,NEEDS_INPUT} from './activity';
it('resolves the actual approval card without losing its description or claiming it is still pending',()=>{
 let parts:ChatPart[]=[];
 for(const part of mapEvent({event:'approval.request',payload:{approval_id:'a',title:'Run tests?',prompt:'Allow the test command'}})!.parts)parts=applyPart(parts,part);
 expect(activityPhrase({turnId:'r',parts})).toBe(NEEDS_INPUT);
 for(const part of mapEvent({event:'approval.resolved',payload:{approval_id:'a',approved:false,request_id:'r'}})!.parts)parts=applyPart(parts,part);
 expect(parts).toEqual([{kind:'confirmation',callId:'a',title:'Run tests?',message:'Allow the test command',decision:'deny'}]);
 expect(activityPhrase({turnId:'r',parts})).not.toBe(NEEDS_INPUT);
});
it('does not invent a decision when a resolution payload has no confirmed result',()=>{
 expect(mapEvent({event:'approval.resolved',payload:{approval_id:'a',resolved:true}})).toBeNull();
});
function events(...rows:Array<Record<string,unknown>>){let parts:ChatPart[]=[];for(const row of rows)for(const part of mapEvent({event:String(row.event),payload:row})?.parts??[])parts=applyPart(parts,part);return parts;}
const request=(approval_id='a',call_id='c',request_id='r')=>({event:'approval.request',approval_id,call_id,request_id,tool:'run_command',title:'Run?'});
const resolve=(approved=false,extra:Record<string,unknown>={})=>({event:'approval.resolved',approval_id:'a',approved,...extra});
it('closes only the correlated permission wait on denial and cancellation',()=>{
 for(const end of [resolve(),{event:'approval.resolved',approval_id:'a',decision:'cancelled'}]){
 const parts=events(request(),request('b','d'),end);
 expect(parts.find(p=>p.kind==='toolInvocation'&&p.callId==='c')).toMatchObject({state:'denied'});
 expect(parts.find(p=>p.kind==='toolInvocation'&&p.callId==='d')).toMatchObject({state:'waitingForConfirmation'});
 }
});
it('grant removes permission wait without inventing execution and permits later real receipts',()=>{
 const parts=events(request(),resolve(true));expect(activityPhrase({turnId:'r',parts})).not.toBe(NEEDS_INPUT);
 expect(parts[0]).toMatchObject({state:'unknown',summary:'Permission granted; execution not yet reported.'});
 expect(events(request(),resolve(true),{event:'tool.started',call_id:'c',tool:'run_command'})[0]).toMatchObject({state:'executing'});
});
it('ignores mismatched identities and malformed identifiers',()=>{
 for(const extra of [{request_id:'other'},{call_id:'other'},{approval_id:{}},{request_id:[]},{call_id:7},{approval_id:''}])expect(events(request(),resolve(false,extra))[0]).toMatchObject({state:'waitingForConfirmation'});
 expect(mapEvent({event:'approval.request',payload:{approval_id:{},call_id:'c'}})).toBeNull();
 expect(mapEvent({event:'approval.resolved',payload:{approved:false}})).toBeNull();
});
it('late resolution and duplicates do not close or reopen newer permission waits',()=>{
 expect(events(request(),request('b'),resolve())[0]).toMatchObject({state:'waitingForConfirmation',approvalId:'b'});
 expect(events(request(),resolve(),request())[0]).toMatchObject({state:'denied'});
 expect(events(request(),{event:'tool.done',call_id:'c',tool:'run_command'},resolve())[0]).toMatchObject({state:'completed'});
});
it('accepts approval ID alias and retains request correlation',()=>{
 const parts=events({...request(),approval_id:undefined,id:'a'},resolve(false,{id:'a',approval_id:undefined,request_id:'r'}));
 expect(parts[0]).toMatchObject({state:'denied',requestId:'r'});
});
it.each(['completed','failed','cancelled','unknown','denied','unsupported','rejected'])('does not rewind observed %s receipt on delayed approval request',state=>{
 const terminal={event:state==='completed'?'tool.done':'tool.failed',call_id:'c',tool:'run_command',outcome:state,request_id:'r'};
 expect(events(terminal,request())[0]).toMatchObject({state,requestId:'r'});
 expect(events({...terminal,request_id:undefined},request())[0]).toMatchObject({state});
});
it('keeps a newer request sharing a call ID separate from an earlier terminal receipt',()=>{
 const terminal={event:'tool.done',call_id:'c',request_id:'old',tool:'run_command'};
 const parts=events(terminal,request(),resolve(false,{request_id:'r'}));
 expect(parts[0]).toMatchObject({state:'completed',requestId:'old'});
 expect(parts.find(p=>p.kind==='toolInvocation'&&p.requestId==='r')).toMatchObject({state:'denied'});
});
it('permission grant without execution does not suppress a new approval',()=>{
 expect(events(request(),resolve(true),request('b'))[0]).toMatchObject({state:'waitingForConfirmation',approvalId:'b'});
});
it('a granted permission wait following tool start is still not a terminal execution receipt',()=>{
 expect(events({event:'tool.started',call_id:'c',request_id:'r'},request(),resolve(true),request('b'))[0]).toMatchObject({state:'waitingForConfirmation',approvalId:'b'});
});

it('preserves persisted terminal tool receipts without a live receipt marker',()=>{
 for(const state of ['completed','failed','cancelled','unknown'] as const){
 let parts:ChatPart[]=[{kind:'toolInvocation',callId:'c',toolName:'run_command',input:null,state}];
 for(const part of mapEvent({event:'approval.request',payload:request()})!.parts)parts=applyPart(parts,part);
 expect(parts[0]).toMatchObject({state});
 }
});
