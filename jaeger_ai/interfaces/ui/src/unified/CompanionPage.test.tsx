import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { CompanionPage } from './CompanionPage';
import type { JaegerSource } from '../api/source';
import { MockSource } from '../api/mock';
vi.mock('./StudioPage', () => ({StudioPage: ({initialSection}: {initialSection:string}) => <div>Media section: {initialSection}</div>}));
vi.mock('../automations/AutomationsPanel', () => ({AutomationsPanel: () => <div>Existing automation controls</div>}));
vi.mock('../library/LibraryPanel', () => ({LibraryPanel: () => <div>Existing document controls</div>}));
afterEach(cleanup);
it('opens saved media first and uses existing document controls', () => {
 const source: JaegerSource=new MockSource(); source.library={} as NonNullable<typeof source.library>;
 render(<CompanionPage page="library" source={source} agents={[]} onNavigate={vi.fn()} />);
 expect(screen.getByText('Media section: library')).toBeInTheDocument();
 fireEvent.click(screen.getByRole('radio',{name:'Documents'}));
 expect(screen.getByText('Existing document controls')).toBeInTheDocument();
});
it('uses the existing automation owner', () => {
 const source: JaegerSource=new MockSource(); source.schedules={} as NonNullable<typeof source.schedules>;
 render(<CompanionPage page="automations" source={source} agents={[]} onNavigate={vi.fn()} />);
 expect(screen.getByText('Existing automation controls')).toBeInTheDocument();
});
it('reports a failed feed request rather than showing a false empty state', async () => {
 const source: JaegerSource=new MockSource(); source.notifications={read:vi.fn().mockRejectedValue(Error('Offline'))} as unknown as NonNullable<typeof source.notifications>;
 render(<CompanionPage page="feed" source={source} agents={[]} onNavigate={vi.fn()} />);
 expect(await screen.findByRole('alert')).toHaveTextContent('Offline');
 expect(screen.queryByText('You are caught up')).not.toBeInTheDocument();
});
it('renders only updates returned by the notification owner', async () => {
 const source: JaegerSource=new MockSource(); source.notifications={read:vi.fn().mockResolvedValue({notifications:[{event_id:1,title:'Build completed',timestamp:1,unread:true,session_id:'saved'}]})} as unknown as NonNullable<typeof source.notifications>;
 render(<CompanionPage page="feed" source={source} agents={[]} onNavigate={vi.fn()} />);
 expect(await screen.findByText('Build completed')).toBeInTheDocument();
});
