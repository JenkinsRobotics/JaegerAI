import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { act } from 'react';
import { expect, it, vi } from 'vitest';
import type { RuntimeTierSnapshot } from '../api/source';
import { RunModeControl } from './RunModeControl';

const snapshot: RuntimeTierSnapshot = {tier:'agent',options:['agent','plan'],descriptions:{agent:'Tools under policy',plan:'Read-only plan'}};
it('uses Gateway options and waits for confirmation before changing the displayed mode', async () => {
 let resolve!: (value:RuntimeTierSnapshot)=>void;
 const host = {runtimeTier:vi.fn().mockResolvedValue(snapshot),setRuntimeTier:vi.fn(()=>new Promise<RuntimeTierSnapshot>(done=>{resolve=done;}))};
 render(<RunModeControl host={host}/>);
 const trigger=await screen.findByRole('button',{name:'Run mode: Agent'});
 fireEvent.click(trigger);
 expect(screen.queryByRole('menuitemradio',{name:/Chat/})).toBeNull();
 const plan=await screen.findByRole('menuitemradio',{name:/Plan Look around/});
 await waitFor(()=>expect(plan).not.toBeDisabled());
 fireEvent.click(plan);
 expect(host.setRuntimeTier).toHaveBeenCalledExactlyOnceWith('plan');
 expect(trigger).toHaveAccessibleName('Run mode: Agent');
 expect(trigger).toBeDisabled();
 await act(async()=>resolve({...snapshot,tier:'plan'}));
 expect(trigger).toHaveAccessibleName('Run mode: Plan');
 expect(screen.queryByRole('menu')).toBeNull();
});
it('preserves the confirmed mode after a lost reply and requires explicit refresh before another change', async () => {
 const host={runtimeTier:vi.fn().mockResolvedValue(snapshot),setRuntimeTier:vi.fn().mockRejectedValue(Error('Connection lost'))};
 render(<RunModeControl host={host}/>);
 const trigger=await screen.findByRole('button',{name:'Run mode: Agent'});
 fireEvent.click(trigger);
 expect(screen.queryByRole('menuitemradio',{name:/Chat/})).toBeNull();
 const plan=await screen.findByRole('menuitemradio',{name:/Plan Look around/});
 await waitFor(()=>expect(plan).not.toBeDisabled());fireEvent.click(plan);
 expect(await screen.findByRole('alert')).toHaveTextContent('Change unconfirmed');
 expect(trigger).toHaveAccessibleName('Run mode: Agent');
 expect(plan).toBeDisabled();fireEvent.click(plan);
 expect(host.setRuntimeTier).toHaveBeenCalledTimes(1);
 host.runtimeTier.mockResolvedValue({...snapshot,tier:'plan'});
 fireEvent.click(trigger); fireEvent.click(trigger);
 await waitFor(()=>expect(trigger).toHaveAccessibleName('Run mode: Plan'));
 expect(host.setRuntimeTier).toHaveBeenCalledTimes(1);
});
it('cannot change run mode during an active turn', async () => {
 const host={runtimeTier:vi.fn().mockResolvedValue(snapshot),setRuntimeTier:vi.fn()};
 render(<RunModeControl host={host} disabled/>);
 const trigger=await screen.findByRole('button',{name:'Run mode: Agent'});
 expect(trigger).toBeDisabled();fireEvent.click(trigger);
 expect(host.setRuntimeTier).not.toHaveBeenCalled();
});
