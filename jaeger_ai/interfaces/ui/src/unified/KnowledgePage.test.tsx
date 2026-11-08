import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { JaegerSource, AgentMemorySnapshot } from '../api/source';
import type { Agent } from '../api/types';
import { KnowledgePage } from './KnowledgePage';
import { AgentMemory } from '../agents/AgentMemory';

vi.mock('../chat/Markdown', () => ({ Markdown: ({text}: {text: string}) => <p>{text}</p> }));
const source = (parts: object) => parts as JaegerSource;
const agents = [{ id: 'A', name: 'Agent A' }, { id: 'B', name: 'Agent B' }] as Agent[];
const deferred = <T,>() => { let resolve!: (v:T)=>void; let reject!: (e:Error)=>void; const promise = new Promise<T>((r,j)=>{resolve=r; reject=j;}); return {promise,resolve,reject}; };
const snapshot = (id: string, notes: string, editable = false): AgentMemorySnapshot => ({agent_id:id, notes, editable, revision:'r1', chars:notes.length, max_chars:1000, prompt_chars:100, loaded_in_specialist_prompt:true,prompt_truncated:false,versions:[]});
const skill = (name:string) => ({name,category:'Tools',description:`${name} description`,lifecycle:'installed'});
const skillDetail = (name:string) => ({...skill(name),origin:`${name} origin`,tier:'1',availability:'available',platforms:[],requires_tools:[],tags:[]});
const tab = (name:string) => fireEvent.click(screen.getByRole('radio',{name}));

describe('Knowledge request ownership',()=>{
 it('ignores a previous skill detail and retries the exact selected skill',async()=>{
  const old=deferred<unknown>();
  const detail=vi.fn().mockReturnValueOnce(old.promise).mockRejectedValueOnce(Error('skill offline')).mockResolvedValue(skillDetail('B'));
  render(<KnowledgePage agents={agents} source={source({skills:async()=>({skills:[skill('A'),skill('B')]}),skillDetail:detail})}/>);
  fireEvent.click(await screen.findByRole('button',{name:'A A description'}));
  await waitFor(()=>expect(detail).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole('button',{name:'B B description'}));
  await screen.findByText('skill offline');
  await act(async()=>old.resolve(skillDetail('A')));
  expect(screen.queryByText('A origin')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Retry'}));
  expect(await screen.findByText('B origin')).toBeInTheDocument();
  expect(detail).toHaveBeenLastCalledWith('B','Tools');
 });
 it('rejects stale skills-list success after a source change and recovers a list error',async()=>{
  const old=deferred<unknown>(); const list=vi.fn().mockRejectedValueOnce(Error('list offline')).mockResolvedValue({skills:[]});
  const view=render(<KnowledgePage agents={agents} source={source({skills:()=>old.promise})}/>);
  await act(async()=>{await new Promise(r=>setTimeout(r,10));});
  view.rerender(<KnowledgePage agents={agents} source={source({skills:list})}/>);
  await screen.findByText('list offline');
  await act(async()=>old.resolve({skills:[skill('Old')]}));
  expect(screen.queryByText('Old')).not.toBeInTheDocument();
  fireEvent.click(screen.getByText('Retry'));
  await screen.findByText('No skills installed');
 });
 it('ignores in-flight memory from the previous agent and rejects identity mismatch',async()=>{
  const old=deferred<AgentMemorySnapshot>();
  const read=vi.fn().mockReturnValueOnce(old.promise).mockResolvedValueOnce(snapshot('A','wrong identity')).mockResolvedValue(snapshot('B','B notes'));
  render(<KnowledgePage agents={agents} source={source({agentMemory:{read}})}/>);tab('Memory');
  await waitFor(()=>expect(read).toHaveBeenCalledWith('A',undefined));
  fireEvent.change(screen.getByLabelText('Agent'),{target:{value:'B'}});
  await screen.findByText('Memory identity mismatch');
  await act(async()=>old.resolve(snapshot('A','late A notes',true)));
  expect(screen.queryByText('late A notes')).not.toBeInTheDocument();
  expect(screen.queryByText('Edit')).not.toBeInTheDocument();
  fireEvent.click(screen.getByText('Retry'));
  await screen.findByText('B notes');
 });
 it('ignores old memory search failures and handles a removed agent without silently switching',async()=>{
  const pending=deferred<AgentMemorySnapshot>(); const read=vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValue({...snapshot('A','current'),search:{query:'new',matches:[],truncated:false,scope:'notes'}});
  const src=source({agentMemory:{read}});const view=render(<KnowledgePage agents={agents} source={src}/>);tab('Memory');
  await waitFor(()=>expect(read).toHaveBeenCalledTimes(1));
  fireEvent.change(screen.getByLabelText('Search memory'),{target:{value:'new'}});
  await screen.findByText('No matches');
  await act(async()=>pending.reject(Error('obsolete search failure')));
  expect(screen.queryByText('obsolete search failure')).not.toBeInTheDocument();
  view.rerender(<KnowledgePage agents={[agents[1]]} source={src}/>);
  await screen.findByText('Select an available agent');
  expect(read).not.toHaveBeenCalledWith('B',expect.anything());
 });
 it('distinguishes no agents and unsupported capabilities',async()=>{
  const read=vi.fn();render(<KnowledgePage agents={[]} source={source({agentMemory:{read}})}/>);
  await screen.findByText('Skills unavailable'); tab('Memory');
  await screen.findByText('No agents available');expect(read).not.toHaveBeenCalled();tab('Library');
  await screen.findByText('Library unavailable');
 });
 it('keeps document detail errors separate from list and ignores late selections',async()=>{
  const old=deferred<unknown>();const read=vi.fn().mockReturnValueOnce(old.promise).mockRejectedValueOnce(Error('document offline')).mockResolvedValue({id:'B',title:'Doc B',content:'B body'});
  render(<KnowledgePage agents={agents} source={source({library:{list:async()=>({documents:[{id:'A',title:'Doc A'},{id:'B',title:'Doc B'}]}),read}})}/>);tab('Library');
  fireEvent.click(await screen.findByRole('button',{name:'Doc A'}));await waitFor(()=>expect(read).toHaveBeenCalledWith('A'));
  fireEvent.click(screen.getByRole('button',{name:'Doc B'}));await screen.findByText('document offline');
  expect(screen.getByRole('button',{name:'Doc A'})).toBeInTheDocument();
  await act(async()=>old.resolve({id:'A',title:'Doc A',content:'stale A body'}));
  expect(screen.queryByText('stale A body')).not.toBeInTheDocument();
  fireEvent.click(screen.getByText('Retry'));await screen.findByText('B body');expect(read).toHaveBeenLastCalledWith('B');
 });
 it('ignores in-flight library search results after a new query',async()=>{
  const old=deferred<unknown>();const search=vi.fn().mockReturnValueOnce(old.promise).mockResolvedValue({results:[]});
  render(<KnowledgePage agents={agents} source={source({library:{list:async()=>({documents:[]}),search}})}/>);tab('Library');
  await screen.findByText('Library is empty');
  fireEvent.change(screen.getByLabelText('Search library'),{target:{value:'old'}});await waitFor(()=>expect(search).toHaveBeenCalledWith('old'));
  fireEvent.change(screen.getByLabelText('Search library'),{target:{value:'new'}});await screen.findByText('No results');
  await act(async()=>old.resolve({results:[{id:'old',title:'obsolete doc'}]}));expect(screen.queryByText('obsolete doc')).not.toBeInTheDocument();
 });
 it('pins the opened memory editor while preventing selection changes',async()=>{
  const controls={read:vi.fn().mockImplementation((id:string)=>Promise.resolve(snapshot(id,`${id} notes`,true)))};
  render(<KnowledgePage agents={agents} source={source({agentMemory:controls})}/>);tab('Memory');
  fireEvent.click(await screen.findByText('Edit'));
  expect(screen.getByLabelText('Agent')).toBeDisabled();
  expect(await screen.findByLabelText('Specialist notes')).toHaveValue('A notes');
 });
 it('isolates the memory editor across agent and backend changes',async()=>{
  const old=deferred<AgentMemorySnapshot>(); const controls={read:vi.fn().mockReturnValue(old.promise),mutate:vi.fn(),operation:vi.fn()};
  const view=render(<AgentMemory agentId="A" controls={controls} onClose={()=>{}}/>);
  const next={...controls,read:vi.fn().mockResolvedValue(snapshot('B','B editor notes',false))};
  view.rerender(<AgentMemory agentId="B" controls={next} onClose={()=>{}}/>);
  expect(await screen.findByLabelText('Specialist notes')).toHaveValue('B editor notes');
  await act(async()=>old.resolve(snapshot('A','A stale editor',true)));
  expect(screen.getByLabelText('Specialist notes')).toHaveValue('B editor notes');
  expect(screen.getByLabelText('Specialist notes')).toBeDisabled();
  expect(screen.getByRole('button',{name:'Save specialist notes'})).toBeDisabled();
  expect(controls.mutate).not.toHaveBeenCalled();
  const newest={...controls,read:vi.fn().mockResolvedValue(snapshot('B','B replacement backend',false))};
  view.rerender(<AgentMemory agentId="B" controls={newest} onClose={()=>{}}/>);
  await waitFor(()=>expect(screen.getByLabelText('Specialist notes')).toHaveValue('B replacement backend'));
 });
 it('retains pending memory intent when a retired backend returns a rejected save',async()=>{
  const id='pending-context-agent';
  const pending=deferred<{ok:boolean;operation_id:string;error:string}>();
  const controls={read:vi.fn().mockResolvedValue(snapshot(id,'original',true)),mutate:vi.fn().mockReturnValue(pending.promise),operation:vi.fn()};
  const view=render(<AgentMemory agentId={id} controls={controls} onClose={()=>{}}/>);
  fireEvent.change(await screen.findByLabelText('Specialist notes'),{target:{value:'my saved draft'}});
  fireEvent.click(screen.getByRole('button',{name:'Save specialist notes'}));
  await waitFor(()=>expect(controls.mutate).toHaveBeenCalledTimes(1));
  const operationId=controls.mutate.mock.calls[0][1].operation_id;
  const operationKey=`jaeger.ui.agent-memory.operation.v1.${id}.${operationId}`;
  const draftKey=`jaeger.ui.agent-memory.draft.v1.${id}`;
  const intent=localStorage.getItem(operationKey),draft=localStorage.getItem(draftKey);
  const next={...controls,read:vi.fn().mockResolvedValue(snapshot(id,'new backend notes',true))};
  view.rerender(<AgentMemory agentId={id} controls={next} onClose={()=>{}}/>);
  await screen.findByRole('button',{name:'Check saved memory action'});
  await act(async()=>pending.resolve({ok:false,operation_id:operationId,error:'old backend refused'}));
  expect(localStorage.getItem(operationKey)).toBe(intent);
  expect(localStorage.getItem(draftKey)).toBe(draft);
  expect(screen.getByLabelText('Specialist notes')).toHaveValue('my saved draft');
  expect(screen.getByRole('button',{name:'Save specialist notes'})).toBeDisabled();
  expect(screen.queryByText(/old backend refused/)).not.toBeInTheDocument();
 });

});
