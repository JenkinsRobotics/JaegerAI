import {act,fireEvent,render,screen,cleanup} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {AudioSettingsPanel} from './AudioSettingsPanel';
import {VoiceMode} from '../chat/VoiceMode';
import {readAudioPreferences,saveAudioPreferences} from './audioPreferences';
import type {VoiceIO} from '../chat/webSpeech';
afterEach(()=>{cleanup();localStorage.clear();vi.restoreAllMocks();});
function io(){return {capability:async()=>({transcription:true,speech:true}),devices:async()=>({microphones:[{deviceId:'desk-mic',label:'Desk microphone'}],speakers:[{deviceId:'desk-speaker',label:'Desk speaker'}]}),capture:vi.fn<VoiceIO['capture']>(()=>new Promise(()=>{})),speak:async()=>{}} satisfies VoiceIO;}
it('uses the same persisted platform-independent device selection in settings and chat',async()=>{
 const adapter=io();const view=render(<AudioSettingsPanel io={adapter}/>);await act(async()=>{});
 fireEvent.change(screen.getByRole('combobox',{name:'Voice microphone'}),{target:{value:'desk-mic'}});fireEvent.change(screen.getByRole('combobox',{name:'Voice speaker'}),{target:{value:'desk-speaker'}});expect(readAudioPreferences()).toEqual({inputId:'desk-mic',outputId:'desk-speaker'});
 view.unmount();render(<VoiceMode io={adapter} busy={false} onTranscript={async()=>true}/>);await act(async()=>fireEvent.click(screen.getByRole('button',{name:'Start voice mode'})));expect(adapter.capture.mock.calls[0][1]).toBe('desk-mic');
});
it('leaves the system default selected and exposes no invented room or proximity',async()=>{
 render(<AudioSettingsPanel io={io()}/>);await act(async()=>{});expect((screen.getByRole('combobox',{name:'Voice speaker'}) as HTMLSelectElement).value).toBe('');expect(document.body.textContent).toContain('System default follows');expect(document.body.textContent).not.toContain('Nearest');
});
it('reports unavailable saved devices and never silently overwrites them',async()=>{
 saveAudioPreferences({inputId:'disconnected',outputId:''});render(<AudioSettingsPanel io={io()}/>);await act(async()=>{});expect(screen.getByText('Saved device unavailable')).toBeTruthy();expect(readAudioPreferences().inputId).toBe('disconnected');
});
it('reports persistence failure without claiming the new route was saved',async()=>{
 render(<AudioSettingsPanel io={io()}/>);await act(async()=>{});vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('Storage unavailable');});fireEvent.change(screen.getByRole('combobox',{name:'Voice speaker'}),{target:{value:'desk-speaker'}});expect(screen.getByRole('alert').textContent).toContain('Storage unavailable');expect(readAudioPreferences().outputId).toBe('');
});
function deferred<T>(){let resolve!:(value:T)=>void;let reject!:(error:Error)=>void;const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
it.each(['capability','devices'] as const)('leaves loading on rejected %s and clears stale success on failed refresh',async(method)=>{
 const adapter=io();const query=vi.spyOn(adapter,method);query.mockRejectedValueOnce(Error('Permission check failed'));
 render(<AudioSettingsPanel io={adapter}/>);await act(async()=>{});expect(screen.queryByText('Checking…')).toBeNull();expect(screen.getByRole('alert').textContent).toBe('Permission check failed');
 await act(async()=>fireEvent.click(screen.getByText('Refresh audio devices')));expect(screen.getByText('Speech services available')).toBeTruthy();
 query.mockRejectedValueOnce(Error('Refresh failed'));await act(async()=>fireEvent.click(screen.getByText('Refresh audio devices')));
 expect(screen.queryByText('Speech services available')).toBeNull();expect(screen.getByText('Check failed')).toBeTruthy();
});
it('shows unavailable and empty inventory without claiming hardware readiness',async()=>{
 render(<AudioSettingsPanel io={{...io(),capability:async()=>({transcription:false,speech:false,reason:'Speech unavailable'}),devices:async()=>({microphones:[],speakers:[]})}}/>);await act(async()=>{});
 expect(screen.getByText('Unavailable')).toBeTruthy();expect(screen.getByText('No microphones listed.')).toBeTruthy();expect(screen.getByText('Speech unavailable')).toBeTruthy();
});
it('ignores old refresh results and preserves saved selection',async()=>{
 saveAudioPreferences({inputId:'saved',outputId:''});const old=deferred<Awaited<ReturnType<VoiceIO['capability']>>>();const adapter:VoiceIO=io();vi.spyOn(adapter,'capability').mockReturnValueOnce(old.promise);
 render(<AudioSettingsPanel io={adapter}/>);expect(screen.getByText('Checking…')).toBeTruthy();expect(screen.getByText('Saved device (not verified)')).toBeTruthy();
 await act(async()=>fireEvent.click(screen.getByText('Refresh audio devices')));await act(async()=>old.resolve({transcription:false,speech:false}));
 expect(screen.getByText('Speech services available')).toBeTruthy();expect(readAudioPreferences().inputId).toBe('saved');
});
it('switches sources and ignores late failure after replacement or unmount',async()=>{
 const old=deferred<Awaited<ReturnType<VoiceIO['capability']>>>();const first={...io(),capability:()=>old.promise,release:vi.fn()};const next={...io(),release:vi.fn()};
 const view=render(<AudioSettingsPanel io={first}/>);view.rerender(<AudioSettingsPanel io={next}/>);await act(async()=>{});expect(first.release).toHaveBeenCalledOnce();
 await act(async()=>old.reject(Error('Obsolete failure')));expect(screen.queryByRole('alert')).toBeNull();expect(screen.getByText('Speech services available')).toBeTruthy();
 view.unmount();expect(next.release).toHaveBeenCalledOnce();
});

it('ignores completion after unmount and releases the source',async()=>{
 const pending=deferred<Awaited<ReturnType<VoiceIO['capability']>>>();const adapter={...io(),capability:()=>pending.promise,release:vi.fn()};
 const view=render(<AudioSettingsPanel io={adapter}/>);view.unmount();await act(async()=>pending.resolve({transcription:true,speech:true}));expect(view.container.textContent).toBe('');expect(adapter.release).toHaveBeenCalledOnce();
});
it.each([null,{}, {transcription:'false',speech:'false'}, {transcription:true}, {transcription:true,speech:true,reason:{}}])('rejects malformed capability data %j',async(value)=>{
 saveAudioPreferences({inputId:'saved',outputId:''});render(<AudioSettingsPanel io={{...io(),capability:async()=>value as Awaited<ReturnType<VoiceIO['capability']>>}}/>);await act(async()=>{});
 expect(screen.getByRole('alert').textContent).toBe('Invalid speech capability response.');expect(screen.queryByText('Speech services available')).toBeNull();expect(readAudioPreferences().inputId).toBe('saved');
});
it.each([null,{}, {microphones:null,speakers:[]}, {microphones:[],speakers:{}}, {microphones:[null],speakers:[]}, {microphones:[{deviceId:7,label:'mic'}],speakers:[]}, {microphones:[],speakers:[{deviceId:'s',label:{}}]}])('rejects malformed device data without crashing %j',async(value)=>{
 render(<AudioSettingsPanel io={{...io(),devices:async()=>value as unknown as Awaited<ReturnType<VoiceIO['devices']>>}}/>);await act(async()=>{});
 expect(screen.getByRole('alert').textContent).toBe('Invalid audio device response.');expect(screen.queryByText('Speech services available')).toBeNull();expect(screen.getByRole('combobox',{name:'Voice microphone'})).toBeTruthy();
});
