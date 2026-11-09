import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen} from '@testing-library/react';
import {mapEvent} from './eventMap';
import {applyPart,type ChatPart} from './host';
import {activityPhrase,NEEDS_INPUT} from './activity';
import {segments,ProgressLine} from './MinimalChat';
import {ApprovalCard} from './ApprovalCard';
afterEach(cleanup);
const approval=(request_id='r',call_id='c')=>({event:'approval.request',payload:{approval_id:'a',request_id,call_id,tool:'run_command'}});
function project(state:string,requestId:string|undefined,next=approval()){
 const terminal={event:state==='completed'?'tool.done':'tool.failed',payload:{request_id:requestId,call_id:'c',tool:'run_command',outcome:state}};
 return [terminal,next].flatMap(event=>mapEvent(event)?.parts??[]).reduce(applyPart,[] as ChatPart[]);
}
function show(parts:ChatPart[]){
 const decide=vi.fn();
 render(<>{segments(parts,'pending').map((seg,index)=>'card'in seg&&seg.card.kind==='confirmation'?<ApprovalCard key={index} title={seg.card.title} message={seg.card.message} decided={seg.card.decision} onDecide={decide}/>:null)}<ProgressLine phrase={activityPhrase({turnId:'r',parts})}/></>);
 return decide;
}
it.each(['completed','failed','cancelled','unknown','denied','rejected','unsupported'])('does not restore interactive permission controls after observed %s',state=>{
 const parts=project(state,'r');const decide=show(parts);
 expect(parts.filter(p=>p.kind==='confirmation'&&!p.decision)).toHaveLength(0);
 expect(parts[0]).toMatchObject({state});
 expect(screen.queryAllByRole('button')).toHaveLength(0);
 expect(document.querySelector('.jg-progress-text')?.textContent).not.toBe(NEEDS_INPUT);
 expect(decide).not.toHaveBeenCalled();
});
it.each([approval('new','c'),approval('r','different')])('retains interactive controls for a different request or call',next=>{
 const parts=project('completed','r',next);show(parts);
 expect(parts.filter(p=>p.kind==='confirmation'&&!p.decision)).toHaveLength(1);
 expect(screen.getByRole('button',{name:'Allow once'})).toBeTruthy();
 expect(screen.getByRole('button',{name:/Deny once/})).toBeTruthy();
 expect(document.querySelector('.jg-progress-text')?.textContent).toBe(NEEDS_INPUT);
});
it('does not fabricate a permission decision for legacy receipts or remove resolved history',()=>{
 const parts=project('completed',undefined);expect(parts.some(p=>p.kind==='confirmation')).toBe(false);
 const history:ChatPart={kind:'confirmation',callId:'old',toolCallId:'c',requestId:'r',title:'Prior approval',message:'Prior request',decision:'approve'};
 const retained=applyPart(parts,history);expect(retained.at(-1)).toEqual(history);
});
