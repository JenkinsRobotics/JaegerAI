/** Synthetic source tests, not live Gateway or browser acceptance. */
import {afterEach, expect, it, vi} from 'vitest';
import {act, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {AgentsRoster} from './AgentsRoster';
import {MockSource} from '../api/mock';
import type {Agent} from '../api/types';

vi.mock('./CharacterRoster', () => ({CharacterRoster: () => null}));
const agent = {id:'specialist:one', name:'Specialist One'} as Agent;
const second = {id:'specialist:two', name:'Specialist Two'} as Agent;
afterEach(() => {localStorage.clear();});
function mount(source = new MockSource(), agents = [agent]) {
 const onNavigate = vi.fn();
 const view = render(<AgentsRoster source={source} store={{agents, summaries:[], seen:{}, loading:false}} refresh={vi.fn()} onNavigate={onNavigate}/>);
 return {...view, source, onNavigate};
}

it('links each historic conversation to its exact encoded session while Open chat stays agent-scoped', async () => {
 const source = new MockSource();
 vi.spyOn(source, 'sessions').mockResolvedValue([
  {session_id:'older /?&', title:'Historic conversation', agent_id:agent.id},
  {session_id:'newer', title:'Newer conversation', agent_id:agent.id},
 ]);
 const {onNavigate} = mount(source);
 fireEvent.click(await screen.findByRole('button', {name:/Historic conversation/}));
 expect(onNavigate).toHaveBeenLastCalledWith('/?agent=specialist%3Aone&session=older%20%2F%3F%26');
 fireEvent.click(screen.getByRole('button', {name:/Newer conversation/}));
 expect(onNavigate).toHaveBeenLastCalledWith('/?agent=specialist%3Aone&session=newer');
 fireEvent.click(screen.getByRole('button', {name:'Open chat'}));
 expect(onNavigate).toHaveBeenLastCalledWith('/chat?agent=specialist%3Aone');
});

it('reports failed conversation reads instead of empty history and recovers on explicit retry', async () => {
 const source = new MockSource();
 const sessions = vi.spyOn(source, 'sessions').mockRejectedValueOnce(new Error('Gateway offline')).mockResolvedValue([]);
 mount(source);
 expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't load conversations: Gateway offline");
 expect(screen.queryByText('No conversations yet.')).toBeNull();
 fireEvent.click(screen.getByRole('button', {name:'Retry conversations'}));
 await screen.findByText('No conversations yet.');
 expect(sessions).toHaveBeenCalledTimes(2);
 expect(screen.queryByRole('alert')).toBeNull();
});

it('reports model read errors without claiming a Gateway default', async () => {
 const source = new MockSource();
 Object.assign(source, {agentHome:vi.fn().mockResolvedValue({session_id:'home'}), modelSettings:{read:vi.fn().mockRejectedValueOnce(new Error('Model read failed')).mockResolvedValue({model:'verified-model'})}});
 mount(source);
 expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't load model: Model read failed");
 expect(screen.queryByText('Gateway default')).toBeNull();
 fireEvent.click(screen.getByRole('button', {name:'Retry model details'}));
 await screen.findByText('verified-model');
 expect(screen.queryByRole('alert')).toBeNull();
});

it('ignores a late history failure after selecting a different agent', async () => {
 const source = new MockSource();
 let rejectOld!: (error:Error) => void;
 vi.spyOn(source, 'sessions').mockImplementation(({agent_id} = {}) => agent_id === agent.id
  ? new Promise((_resolve, reject) => {rejectOld = reject;})
  : Promise.resolve([{session_id:'two-history', title:'Second history', agent_id:second.id}]));
 mount(source, [agent,second]);
 await waitFor(() => expect(rejectOld).toBeTypeOf('function'));
 fireEvent.click(screen.getByRole('button', {name:/^Specialist Two/}));
 await screen.findByRole('button', {name:/Second history/});
 await act(async () => rejectOld(new Error('Old agent failed')));
 await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
 expect(screen.getByRole('button', {name:/Second history/})).toBeVisible();
});
