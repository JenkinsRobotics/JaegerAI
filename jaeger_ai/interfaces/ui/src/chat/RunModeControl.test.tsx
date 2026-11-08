import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { act } from 'react';
import { expect, it, vi } from 'vitest';
import type { RuntimeTierSnapshot } from '../api/source';
import { RunModeControl } from './RunModeControl';

const snapshot: RuntimeTierSnapshot = {tier:'agent',options:['chat','agent','jaeger'],descriptions:{chat:'No tools',agent:'Tools under policy',jaeger:'Resident mode'}};
it('uses Gateway options and waits for confirmation before changing the displayed mode', async () => {
 let resolve!: (value:RuntimeTierSnapshot)=>void;
 const host = {runtimeTier:vi.fn().mockResolvedValue(snapshot),setRuntimeTier:vi.fn(()=>new Promise<RuntimeTierSnapshot>(done=>{resolve=done;}))};
 render(<RunModeControl host={host}/>);
 const trigger=await screen.findByRole('button',{name:'Run mode: Agent'});
 fireEvent.click(trigger);
 const chat=await screen.findByRole('menuitemradio',{name:/Chat No tools/});
 await waitFor(()=>expect(chat).not.toBeDisabled());
 fireEvent.click(chat);
 expect(host.setRuntimeTier).toHaveBeenCalledExactlyOnceWith('chat');
 expect(trigger).toHaveAccessibleName('Run mode: Agent');
 expect(trigger).toBeDisabled();
 await act(async()=>resolve({...snapshot,tier:'chat'}));
 expect(trigger).toHaveAccessibleName('Run mode: Chat');
 expect(screen.queryByRole('menu')).toBeNull();
});
it('preserves the confirmed mode after a lost reply and requires explicit refresh before another change', async () => {
 const host={runtimeTier:vi.fn().mockResolvedValue(snapshot),setRuntimeTier:vi.fn().mockRejectedValue(Error('Connection lost'))};
 render(<RunModeControl host={host}/>);
 const trigger=await screen.findByRole('button',{name:'Run mode: Agent'});
 fireEvent.click(trigger);
 const chat=await screen.findByRole('menuitemradio',{name:/Chat No tools/});
 await waitFor(()=>expect(chat).not.toBeDisabled());fireEvent.click(chat);
 expect(await screen.findByRole('alert')).toHaveTextContent('Change unconfirmed');
 expect(trigger).toHaveAccessibleName('Run mode: Agent');
 expect(chat).toBeDisabled();fireEvent.click(chat);
 expect(host.setRuntimeTier).toHaveBeenCalledTimes(1);
 host.runtimeTier.mockResolvedValue({...snapshot,tier:'chat'});
 fireEvent.click(screen.getByRole('button',{name:'Refresh run mode'}));
 await waitFor(()=>expect(trigger).toHaveAccessibleName('Run mode: Chat'));
 expect(host.setRuntimeTier).toHaveBeenCalledTimes(1);
});
it('cannot change run mode during an active turn', async () => {
 const host={runtimeTier:vi.fn().mockResolvedValue(snapshot),setRuntimeTier:vi.fn()};
 render(<RunModeControl host={host} disabled/>);
 const trigger=await screen.findByRole('button',{name:'Run mode: Agent'});
 expect(trigger).toBeDisabled();fireEvent.click(trigger);
 expect(host.setRuntimeTier).not.toHaveBeenCalled();
});
