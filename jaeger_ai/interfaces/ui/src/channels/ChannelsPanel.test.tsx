import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect,it,vi} from 'vitest';
import {ChannelsPanel} from './ChannelsPanel';
import type {JaegerSource} from '../api/source';

(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;

it('maps loading, empty, error, and retained channel cards to WidgetCard states',async()=>{
 let resolve!: (value: Awaited<ReturnType<NonNullable<JaegerSource['channels']>>>)=>void;
 const channels=vi.fn().mockImplementationOnce(()=>new Promise(r=>{resolve=r;}))
   .mockRejectedValueOnce(Error('offline'));
 const source={channels} as unknown as JaegerSource;
 const host=document.createElement('div'),root=createRoot(host);
 const state=(value:string)=>host.querySelector(`[data-state="${value}"]`);
 try{
  await act(async()=>root.render(<ChannelsPanel source={source}/>));
  expect(state('loading')?.textContent).toContain('Reading channel status');
  await act(async()=>resolve({scope:'current_gateway_process_only',channels:[]}));
  expect(state('empty')?.textContent).toContain('No channels registered');
  await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Refresh channel status')!.click());
  expect(state('error')?.textContent).toContain('Previous status retained');
  expect(state('empty')).not.toBeNull();
 }finally{await act(async()=>root.unmount());}
});
