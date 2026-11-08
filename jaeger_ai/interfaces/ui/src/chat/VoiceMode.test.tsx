import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { VoiceMode } from './VoiceMode';
import type { VoiceIO } from './webSpeech';
import { speechChunks } from './webSpeech';
import { cleanup } from '@testing-library/react';
afterEach(()=>{cleanup();localStorage.clear();});
function fakeIO(){return {capability:vi.fn(async()=>({transcription:true,speech:true})),devices:vi.fn(async()=>({microphones:[],speakers:[]})),capture:vi.fn<VoiceIO['capture']>(()=>new Promise<string>(()=>{})),speak:vi.fn(async(_text:string,_signal:AbortSignal,_output:string)=>{})} satisfies VoiceIO;}
it('does not open a microphone until requested and closes only its own capture',async()=>{
 const io=fakeIO(),submit=vi.fn(async(_text:string)=>true);render(<VoiceMode io={io} onTranscript={submit} busy={false}/>);
 expect(io.capability).not.toHaveBeenCalled();expect(io.capture).not.toHaveBeenCalled();
 await act(async()=>fireEvent.click(screen.getByRole('button',{name:'Start voice mode'})));
 expect(io.capture).toHaveBeenCalledTimes(1);const signal=io.capture.mock.calls[0][0];
 fireEvent.click(screen.getByRole('button',{name:'Stop voice mode'}));expect(signal.aborted).toBe(true);expect(submit).not.toHaveBeenCalled();
});
it('uses the existing turn callback, speaks the new reply once, and resumes listening',async()=>{
 const io=fakeIO();let heard!:(text:string)=>void;io.capture.mockImplementationOnce(()=>new Promise(resolve=>{heard=resolve;}));
 const submit=vi.fn(async(_text:string)=>true);const props={io,onTranscript:submit};const view=render(<VoiceMode {...props} busy={false} reply={{id:'old',text:'Do not replay'}}/>);
 await act(async()=>fireEvent.click(screen.getByRole('button',{name:'Start voice mode'})));
 await act(async()=>heard('Use the compact layout'));expect(submit).toHaveBeenCalledWith('Use the compact layout');expect(io.speak).not.toHaveBeenCalled();
 await act(async()=>view.rerender(<VoiceMode {...props} busy={false} reply={{id:'new',text:'The layout is compact.'}}/>));
 expect(io.speak).toHaveBeenCalledTimes(1);expect(io.speak.mock.calls[0][0]).toBe('The layout is compact.');expect(io.capture).toHaveBeenCalledTimes(3);
 view.rerender(<VoiceMode {...props} busy={false} reply={{id:'new',text:'The layout is compact.'}}/>);expect(io.speak).toHaveBeenCalledTimes(1);
});
it('shows a visible error for rejected voice delivery and does not loop or replay',async()=>{
 const io=fakeIO();io.capture.mockResolvedValueOnce('Keep this transcript');render(<VoiceMode io={io} busy onTranscript={async()=>false}/>);
 await act(async()=>fireEvent.click(screen.getByRole('button',{name:'Start voice mode'})));
 expect(screen.getByRole('alert').textContent).toContain('transcript is preserved');expect(io.capture).toHaveBeenCalledTimes(1);expect(io.speak).not.toHaveBeenCalled();
});
it('does not start capture after a capability probe resolves on a closed panel',async()=>{
 const io=fakeIO();let finish!:(caps:{transcription:boolean;speech:boolean})=>void;io.capability.mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));render(<VoiceMode io={io} busy={false} onTranscript={async()=>true}/>);
 fireEvent.click(screen.getByRole('button',{name:'Start voice mode'}));fireEvent.click(screen.getByRole('button',{name:'Stop voice mode'}));await act(async()=>finish({transcription:true,speech:true}));expect(io.capture).not.toHaveBeenCalled();
});
it('splits long replies within the existing speech endpoint limit without dropping text',()=>{
 const body='A sentence with words. '.repeat(80).trim();const chunks=speechChunks(body);expect(chunks.length).toBeGreaterThan(1);expect(chunks.every(chunk=>chunk.length<=500)).toBe(true);expect(chunks.join(' ')).toBe(body);
});
it('reports microphone startup until the recorder actually signals readiness',async()=>{
 const io=fakeIO();let ready!:()=>void;
 io.capture.mockImplementation((_signal,_input,_level,onReady)=>{ready=()=>onReady(()=>{});return new Promise(()=>{});});
 render(<VoiceMode io={io} busy={false} onTranscript={async()=>true}/>);
 await act(async()=>fireEvent.click(screen.getByRole('button',{name:'Start voice mode'})));
 expect(screen.getByRole('status').textContent).toContain('Starting microphone');
 await act(async()=>ready());expect(screen.getByRole('status').textContent).toContain('Listening');
});
it('tests the speaker without submitting a chat or retaining the microphone',async()=>{
 const io=fakeIO(),submit=vi.fn(async(_text:string)=>true);render(<VoiceMode io={io} busy={false} onTranscript={submit}/>);
 await act(async()=>fireEvent.click(screen.getByRole('button',{name:'Start voice mode'})));
 const signal=io.capture.mock.calls[0][0];
 await act(async()=>fireEvent.click(screen.getByRole('button',{name:'Test speaker'})));
 expect(signal.aborted).toBe(true);expect(io.speak).toHaveBeenCalledWith('Jaeger voice is connected.',expect.any(AbortSignal),'',expect.any(Function));expect(submit).not.toHaveBeenCalled();expect(io.capture).toHaveBeenCalledTimes(1);
 expect(screen.getByRole('status').textContent).toContain('Ready to listen');
});

it('continues accepting spoken follow-ups while Gateway work is active',async()=>{
 const io=fakeIO();const phrases:Array<(text:string)=>void>=[];io.capture.mockImplementation(()=>new Promise(resolve=>phrases.push(resolve)));const submit=vi.fn(async(_text:string)=>true);
 render(<VoiceMode io={io} busy onTranscript={submit}/>);await act(async()=>fireEvent.click(screen.getByRole('button',{name:'Start voice mode'})));
 await act(async()=>phrases[0]('Keep working on the tests'));expect(io.capture).toHaveBeenCalledTimes(2);
 await act(async()=>phrases[1]('Use the existing runtime'));expect(submit.mock.calls.map(call=>call[0])).toEqual(['Keep working on the tests','Use the existing runtime']);expect(io.capture).toHaveBeenCalledTimes(3);expect(io.speak).not.toHaveBeenCalled();
});
it('interrupts playback on new speech when the input adapter has echo cancellation, without cancelling Gateway work',async()=>{
 const io={...fakeIO(),fullDuplex:true};const phrases:Array<(text:string)=>void>=[];io.capture.mockImplementation(()=>new Promise(resolve=>phrases.push(resolve)));io.speak.mockImplementation(()=>new Promise(()=>{}));const submit=vi.fn(async(_text:string)=>true);
 const view=render(<VoiceMode io={io} busy={false} onTranscript={submit}/>);await act(async()=>fireEvent.click(screen.getByRole('button',{name:'Start voice mode'})));await act(async()=>phrases[0]('Explain this'));
 const captureSignal=io.capture.mock.calls[1][0];await act(async()=>view.rerender(<VoiceMode io={io} busy={false} onTranscript={submit} reply={{id:'answer',text:'This is an explanation.'}}/>));
 expect(captureSignal.aborted).toBe(false);const playback=io.speak.mock.calls[0][1];await act(async()=>io.capture.mock.calls[1][4]?.());expect(playback.aborted).toBe(true);expect(captureSignal.aborted).toBe(false);expect(submit).toHaveBeenCalledTimes(1);
 await act(async()=>phrases[1]('Make it shorter'));expect(submit).toHaveBeenLastCalledWith('Make it shorter');
});
