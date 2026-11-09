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
