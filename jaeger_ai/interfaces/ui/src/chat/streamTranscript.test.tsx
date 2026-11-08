import {render,screen,fireEvent} from '@testing-library/react';
import {expect,it} from 'vitest';
import {segments,ActivityFold} from './MinimalChat';
import {AgentActivity,agentActivity} from './AgentActivity';
import {STREAM_STYLES} from './streamStyle';
import type {ChatPart,ChatTurn} from './host';
const tool=(id:string):ChatPart=>({kind:'toolInvocation',callId:id,toolName:'shell',input:{command:'npm test'},state:'completed',output:'2 tests passed'});
it('keeps commentary and separate tool groups in chronological order after replay',()=>{
 const parts:ChatPart[]=[{kind:'markdownContent',text:'Inspecting the app'},tool('a'),tool('b'),{kind:'markdownContent',text:'Found the cause'},tool('c'),{kind:'confirmation',callId:'c',title:'Approve',message:'Continue?'},{kind:'markdownContent',text:'Done'}];
 for(const state of ['pending','complete'] as const){
  const rows=segments(parts,state);
  expect(rows.map(r=>'bubble'in r?'text':'activity'in r?'tools':'card'in r?'card':'marker')).toEqual(['text','tools','text','tools','card','text']);
  expect(rows.flatMap(r=>'bubble'in r?r.bubble:'activity'in r?r.activity:'card'in r?[r.card]:[r.marker])).toEqual(parts);
 }
});
it('expands grouped activity and the retained tool result without hiding commentary',()=>{
 render(<ActivityFold parts={[tool('a')]} live={false} links={{onCopy:()=>{},onOpen:()=>{}}} style={STREAM_STYLES.instant}/>);
 fireEvent.click(screen.getByRole('button',{name:/Show activity/}));
 expect(screen.getByText('2 tests passed')).toBeTruthy();
 expect(screen.getByText('2 tests passed').closest('details')?.open).toBe(false);
 fireEvent.click(screen.getByText('npm test'));
});
it('retains unknown terminal tool states instead of declaring success',()=>{
 const parts:ChatPart[]=[{...tool('a'),state:'executing'} as ChatPart];
 expect(segments(parts,'complete')[0]).toMatchObject({activity:[{state:'unknown'}]});
});
it('agent chip uses real handoff events and does not claim replies are finished work',()=>{
 const turns:ChatTurn[]=[{turnId:'t',message:'Help',state:'pending',parts:[{kind:'handoff',handoffId:'h',agentId:'review',agentName:'Reviewer',direction:'to',count:1,status:'delivered'}]}];
 expect(agentActivity(turns)[0].status).toBe('Messaged');
 turns[0].parts.push({kind:'handoff',handoffId:'h',agentId:'review',agentName:'Reviewer',direction:'from',count:1});
 expect(agentActivity(turns)[0].status).toBe('Replied');
 render(<AgentActivity turns={turns}/>);
 expect(screen.getByText('1 agent')).toBeTruthy();
 expect(screen.getByText('Reviewer')).toBeTruthy();
 expect(screen.queryByText('Finished')).toBeNull();
});
