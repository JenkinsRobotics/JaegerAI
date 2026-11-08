import {describe,expect,it} from 'vitest';
import {mapEvent} from './eventMap';
import {messagesToTurns} from './webHost';
import {applyPart,type ChatPart} from './host';
import type {PersistedPart} from '../api/types';
import {partitionChatParts} from './workGrouping';

const fixtures = [
 {event:'turn.plan',type:'plan',data:{plan:[{step:'Read files',status:'in_progress'}],explanation:'Check the evidence'}},
 {event:'turn.checkpoint',type:'checkpoint',data:{text:'Found the file'}},
 {event:'turn.progress',type:'progress',data:{text:'Checking'}},
 {event:'sources',type:'sources',data:{sources:[{kind:'url',location:'https://example.com',title:'Reference'}]}},
 {event:'search.count',type:'search_count',data:{searches:3,completed:2,failed:1}},
 {event:'follow_ups',type:'follow_ups',data:{follow_ups:['Explain more']}},
];
describe('live and restored stream extras',()=>{
 it.each(fixtures)('$event survives repeated restores with the same presentation',({event,type,data})=>{
  const live=mapEvent({event,payload:data})?.parts;
  expect(live?.length).toBe(1);
  for(let i=0;i<3;i++){
   const restored=messagesToTurns([{role:'user',content:'question',request_id:'r'},{role:'assistant',request_id:'r',parts:[{type,...data} as PersistedPart]}])[0].parts;
   expect(restored).toEqual(live);
  }
 });
 it('updates plans in place instead of duplicating them',()=>{
  let parts:ChatPart[]=[];
  for(const status of ['pending','in_progress','completed']){
   const part=mapEvent({event:'turn.plan',payload:{plan:[{step:'Read',status}]}})!.parts[0];
   parts=applyPart(parts,part);
  }
  expect(parts).toHaveLength(1);
  expect(parts[0]).toMatchObject({plan:[{status:'completed'}]});
  expect(partitionChatParts(parts).work).toHaveLength(1);
 });
 it('rejects malformed extras and never treats source content as executable',()=>{
  expect(mapEvent({event:'search.count',payload:{searches:1,completed:9,failed:0}})).toBeNull();
  expect(mapEvent({event:'turn.plan',payload:{plan:[null,{step:{}}]}})).toBeNull();
  expect(mapEvent({event:'follow_ups',payload:{follow_ups:[{},' ', 'x'.repeat(161)]}})).toBeNull();
 });
});
