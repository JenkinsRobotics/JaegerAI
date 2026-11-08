/** Production shell + roster routing with synthetic API and ChatPane mount probe.
 * Does not establish browser visual or live Gateway acceptance. */
import {afterEach, expect, it, vi} from 'vitest';
import {act, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {MockSource} from '../api/mock';
import {StableDemo, DEMO_SESSION_KEY} from './StableDemo';
import {navigate} from '../shell/router';
vi.mock('../chat/ChatPane', () => ({ChatPane: ({sessionId}:{sessionId:string}) => <div data-testid="selected-chat">{sessionId}</div>}));
vi.mock('../unified/CharacterRoster', () => ({CharacterRoster: () => null}));
afterEach(() => {localStorage.clear(); history.replaceState(null,'','/');});
function sourceWithHistory() {
 const source = new MockSource();
 vi.spyOn(source,'agents').mockResolvedValue([{id:'specialist',name:'Specialist',primary:true}]);
 vi.spyOn(source,'agentsSummary').mockResolvedValue([]);
 vi.spyOn(source,'sessions').mockResolvedValue([
  {session_id:'historic /?&',title:'Historic work',agent_id:'specialist'},
  {session_id:'latest',title:'Latest work',agent_id:'specialist'},
 ]);
 const home = vi.fn().mockResolvedValue({session_id:'home'});
 Object.assign(source,{agentHome:home});
 vi.spyOn(source,'session').mockImplementation(async id => ({session_id:id,agent_id:'specialist'} as never));
 return {source,home};
}
it('opens the selected roster conversation, not agent home, including reload and Back/Forward', async () => {
 history.replaceState(null,'','/agents');
 localStorage.setItem(DEMO_SESSION_KEY,'unrelated');
 const {source,home} = sourceWithHistory();
 const create = vi.spyOn(source,'createSession');
 const view = render(<StableDemo source={source}/>);
 const historic = await screen.findByRole('button',{name:/Historic work/},{timeout:8000});
 // Inspectors may read the home model. Navigation must not resolve a home again.
 const homeCalls = home.mock.calls.length;
 fireEvent.click(historic);
 await waitFor(() => expect(screen.getByTestId('selected-chat')).toHaveTextContent('historic /?&'));
 expect(new URLSearchParams(location.search).get('session')).toBe('historic /?&');
 expect(home).toHaveBeenCalledTimes(homeCalls);
 expect(create).not.toHaveBeenCalled();
 expect(localStorage.getItem(DEMO_SESSION_KEY)).toBe('historic /?&');
 view.unmount();
 render(<StableDemo source={source}/>);
 await waitFor(() => expect(screen.getByTestId('selected-chat')).toHaveTextContent('historic /?&'));
 act(() => navigate('/?agent=specialist&session=latest'));
 await waitFor(() => expect(screen.getByTestId('selected-chat')).toHaveTextContent('latest'));
 await act(async () => {history.back(); await new Promise(resolve => setTimeout(resolve,30));});
 await waitFor(() => expect(screen.getByTestId('selected-chat')).toHaveTextContent('historic /?&'));
 await act(async () => {history.forward(); await new Promise(resolve => setTimeout(resolve,30));});
 await waitFor(() => expect(screen.getByTestId('selected-chat')).toHaveTextContent('latest'));
 expect(home).toHaveBeenCalledTimes(homeCalls);
 expect(create).not.toHaveBeenCalled();
});
it.each(['session not found','Gateway unavailable'])('keeps an exact historic link on %s without falling back or creating a chat', async failure => {
 history.replaceState(null,'','/?agent=specialist&session=missing');
 const {source,home} = sourceWithHistory();
 vi.mocked(source.session).mockRejectedValue(new Error(failure));
 const create = vi.spyOn(source,'createSession');
 render(<StableDemo source={source}/>);
 await screen.findByText(failure);
 expect(screen.queryByTestId('selected-chat')).toBeNull();
 expect(new URLSearchParams(location.search).get('session')).toBe('missing');
 expect(home).not.toHaveBeenCalled();
 expect(create).not.toHaveBeenCalled();
 expect(screen.getByRole('heading',{name:failure === 'session not found' ? 'Conversation unavailable' : 'Waiting to reconnect'})).toBeVisible();
});
it('ignores a late session response after a newer exact conversation selection', async () => {
 history.replaceState(null,'','/?agent=specialist&session=slow');
 const {source,home} = sourceWithHistory();
 let resolveSlow!: (value:never) => void;
 vi.mocked(source.session).mockImplementation(id => id === 'slow' ? new Promise(resolve => {resolveSlow = resolve;}) : Promise.resolve({session_id:id,agent_id:'specialist'} as never));
 render(<StableDemo source={source}/>);
 await waitFor(() => expect(resolveSlow).toBeTypeOf('function'));
 act(() => navigate('/?agent=specialist&session=latest'));
 await waitFor(() => expect(screen.getByTestId('selected-chat')).toHaveTextContent('latest'));
 expect(vi.mocked(source.session).mock.calls.filter(([id]) => id === 'slow')).toHaveLength(1);
 await act(async () => resolveSlow({session_id:'slow',agent_id:'other'} as never));
 expect(screen.getByTestId('selected-chat')).toHaveTextContent('latest');
 expect(home).not.toHaveBeenCalled();
});
