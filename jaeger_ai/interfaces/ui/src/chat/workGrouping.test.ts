import {describe,expect,it} from 'vitest';
import {partitionChatParts} from './workGrouping';
import {segments} from './MinimalChat';
import type {ChatPart} from './host';
describe('shared IDE/browser work grouping',()=>{
 it('preserves every part once and leaves interactive cards and errors outside work',()=>{
  const parts:ChatPart[]=[
   {kind:'markdownContent',text:"I'll inspect it"},
   {kind:'thinking',text:'summary'},
   {kind:'confirmation',callId:'c',title:'Approve',message:'Run?'},
   {kind:'toolInvocation',callId:'c',toolName:'shell',input:{},state:'completed'},
   {kind:'question',callId:'q',title:'Which file?',options:[]},
   {kind:'warning',message:'Important warning'},
   {kind:'error',message:'Failure'},
   {kind:'markdownContent',text:'The result'},
  ];
  const {work,visible}=partitionChatParts(parts);
  expect(work.map(r=>r.index)).toEqual([0,1,3]);
  expect(visible.map(r=>r.index)).toEqual([2,4,5,6,7]);
  expect([...work,...visible].sort((a,b)=>a.index-b.index).map(r=>r.part)).toEqual(parts);
  expect(segments(parts).filter(s=>'card' in s)).toHaveLength(2);
 });
 it('does not classify by wording, or hide a plain answer',()=>{
  const parts:ChatPart[]=[{kind:'markdownContent',text:"Let me explain the answer."}];
  expect(partitionChatParts(parts).work).toHaveLength(0);
 });
 it('keeps all intermediate rounds in order, without duplicating the final answer',()=>{
  const parts:ChatPart[]=[{kind:'markdownContent',text:'First update'},{kind:'progress',message:'Checking'},
   {kind:'markdownContent',text:'Second update'},{kind:'toolInvocation',callId:'c',toolName:'read',input:{},state:'completed'},
   {kind:'markdownContent',text:'Final answer'}];
  expect(partitionChatParts(parts).work.map(r=>r.index)).toEqual([0,1,2,3]);
  expect(partitionChatParts(parts).visible.map(r=>r.index)).toEqual([4]);
 });
});
