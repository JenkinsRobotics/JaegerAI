import {render,screen,fireEvent} from '@testing-library/react';
import {expect,it} from 'vitest';
import {segments,ActivityFold} from './MinimalChat';
import {AgentActivity,agentActivity} from './AgentActivity';
import {STREAM_STYLES} from './streamStyle';
import type {ChatPart,ChatTurn} from './host';
import {applyPart} from './host';
import {mapEvent} from './eventMap';
const tool=(id:string):ChatPart=>({kind:'toolInvocation',callId:id,toolName:'shell',input:{command:'npm test'},state:'completed',output:'2 tests passed'});
it('keeps commentary and separate tool groups in chronological order after replay',()=>{
 const parts:ChatPart[]=[{kind:'markdownContent',text:'Inspecting the app'},tool('a'),tool('b'),{kind:'markdownContent',text:'Found the cause'},tool('c'),{kind:'confirmation',callId:'c',title:'Approve',message:'Continue?'},{kind:'markdownContent',text:'Done'}];
 for(const state of ['pending','complete'] as const){
  const rows=segments(parts,state);
  expect(rows.map(r=>'bubble'in r?'text':'activity'in r?'tools':'card'in r?'card':'marker')).toEqual(['text','tools','text','tools','card','text']);
  expect(rows.flatMap(r=>'bubble'in r?r.bubble:'activity'in r?r.activity:'card'in r?[r.card]:'diagnostic'in r?r.diagnostic:['guidance' in r?r.guidance:r.marker])).toEqual(parts);
 }
});
it('reconciles live provisional text into commentary and one explicit final result',()=>{
 const events=[
  {event:'turn.delta',payload:{delta:'I’ll inspect it.',content_type:'provisional',item_id:'text-1'}},
  {event:'turn.progress',payload:{message:'Reading package.json',content_type:'commentary'}},
  {event:'tool.started',payload:{call_id:'c1',tool:'read_file',input:'package.json'}},
  {event:'tool.completed',payload:{call_id:'c1',tool:'read_file',summary:'Read package.json'}},
  {event:'turn.delta',payload:{delta:'The dependency is current.',content_type:'provisional',item_id:'text-2'}},
  {event:'turn.finish',payload:{output:'The dependency is current.'}},
 ];
 const parts=events.flatMap(event=>mapEvent(event)?.parts??[]).reduce(applyPart,[] as ChatPart[]);
 expect(parts.filter(p=>p.kind==='markdownContent')).toEqual([
  {kind:'markdownContent',text:'I’ll inspect it.',role:'commentary',itemId:'text-1'},
  {kind:'markdownContent',text:'The dependency is current.',role:'final',itemId:'final'},
 ]);
 expect(parts.find(p=>p.kind==='toolInvocation')).toMatchObject({summary:'Read package.json',state:'completed'});
 expect(segments(parts,'complete').map(row=>'bubble'in row?'text':'activity'in row?'activity':'other')).toEqual(['text','activity','text']);
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
it('shows retained reasoning as its own expandable thought row',()=>{
 const rows=segments([{kind:'thinking',text:'private diagnostic',durationMs:2400},tool('a')],'complete');
 expect(rows.map(row=>'activity'in row?row.activity.map(part=>part.kind):[])).toEqual([['thinking'],['toolInvocation']]);
 render(<ActivityFold parts={[{kind:'thinking',text:'private diagnostic',durationMs:2400}]} live={false} links={{onCopy:()=>{},onOpen:()=>{}}} style={STREAM_STYLES.instant}/>);
 expect(screen.getByText('Thought for 2 s')).toBeTruthy();
 expect(screen.queryByText('private diagnostic')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:/Show activity/}));
 expect(screen.getByText('private diagnostic')).toBeTruthy();
});
it('keeps model receipts outside assistant answer bubbles',()=>{
 const rows=segments([
  {kind:'markdownContent',text:'Done',role:'final',itemId:'final'},
  {kind:'modelIdentity',actualModel:null,scope:'unknown'},
 ],'complete');
 expect(rows).toEqual([
  {bubble:[{kind:'markdownContent',text:'Done',role:'final',itemId:'final'}]},
  {diagnostic:[{kind:'modelIdentity',actualModel:null,scope:'unknown'}]},
 ]);
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
it('renders repeated steering messages in order and deduplicates by steering identity',()=>{
 let parts:ChatPart[]=[{kind:'markdownContent',text:'Working',role:'commentary'}];
 for(const steeringId of ['one','one','two']){
  const mapped=mapEvent({event:'turn.steer',payload:{text:'Repeat',steering_id:steeringId}})!;
  parts=mapped.parts.reduce(applyPart,parts);
 }
 parts=applyPart(parts,{kind:'markdownContent',text:'Done',role:'final'});
 const rows=segments(parts,'complete');expect(rows.map(row=>'guidance' in row?row.guidance.steeringId:'assistant')).toEqual(['assistant','one','two','assistant']);
});
