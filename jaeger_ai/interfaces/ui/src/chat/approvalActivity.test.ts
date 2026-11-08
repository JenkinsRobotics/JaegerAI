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
