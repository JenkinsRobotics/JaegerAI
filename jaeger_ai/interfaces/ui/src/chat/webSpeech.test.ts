import { afterEach, expect, it, vi } from 'vitest';
import { BrowserVoiceIO } from './webSpeech';
afterEach(()=>{vi.unstubAllGlobals();vi.useRealTimers();});
function audio(){
 const source={buffer:null,onended:null as null|(()=>void),connect:vi.fn(),disconnect:vi.fn(),start:vi.fn(),stop:vi.fn()};
 const context={state:'running',destination:{},resume:vi.fn(async()=>{}),close:vi.fn(async()=>{}),decodeAudioData:vi.fn(async()=>({duration:1})),createBufferSource:vi.fn(()=>source)};
 vi.stubGlobal('AudioContext',vi.fn(function(){return context;}));
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,blob:async()=>({type:'audio/wav',arrayBuffer:async()=>new ArrayBuffer(4)})})));
 return {source,context};
}
async function settle(){for(let i=0;i<10;i++)await Promise.resolve();}
it('renders decoded speech on the user-unlocked context and waits for the real ended event',async()=>{
 const {source,context}=audio(),io=new BrowserVoiceIO(),playing=vi.fn();await io.prepare();let finished=false;
 const result=io.speak('Hello',new AbortController().signal,'',playing).then(()=>{finished=true;});await settle();
 expect(context.decodeAudioData).toHaveBeenCalledTimes(1);expect(source.start).toHaveBeenCalledTimes(1);expect(playing).toHaveBeenCalledTimes(1);expect(finished).toBe(false);
 source.onended?.();await result;expect(finished).toBe(true);expect(source.disconnect).toHaveBeenCalled();io.release();expect(context.close).toHaveBeenCalled();
});
it('stops only its own playback on abort',async()=>{
 const {source}=audio(),abort=new AbortController();const result=new BrowserVoiceIO().speak('Hello',abort.signal,'');const rejection=expect(result).rejects.toMatchObject({name:'AbortError'});await settle();abort.abort();await rejection;expect(source.stop).toHaveBeenCalledTimes(1);expect(source.disconnect).toHaveBeenCalled();
});
it('reports a stalled audio engine instead of saying speaking forever',async()=>{
 vi.useFakeTimers();const {source}=audio();const result=new BrowserVoiceIO().speak('Hello',new AbortController().signal,'');const rejection=expect(result).rejects.toThrow('Audio playback did not finish');await settle();await vi.advanceTimersByTimeAsync(15000);await rejection;expect(source.stop).toHaveBeenCalled();
});

it('keeps listening through quiet periods without sending silence or retaining unbounded audio',async()=>{
 vi.useFakeTimers();const {context}=audio();let recordings=0;const stopTrack=vi.fn();
 Object.assign(context,{createMediaStreamSource:()=>({connect:vi.fn(),disconnect:vi.fn()}),createAnalyser:()=>({fftSize:1024,disconnect:vi.fn(),getFloatTimeDomainData:(samples:Float32Array)=>samples.fill(0)})});
 vi.stubGlobal('navigator',{mediaDevices:{getUserMedia:vi.fn(async()=>({getTracks:()=>[{stop:stopTrack}],getAudioTracks:()=>[{getSettings:()=>({echoCancellation:true})}]}))}});
 class Recorder {static isTypeSupported(){return true;}state='inactive';onstop?:()=>void;ondataavailable?:()=>void;start(){this.state='recording';recordings++;}stop(){this.state='inactive';queueMicrotask(()=>this.onstop?.());}}
 vi.stubGlobal('MediaRecorder',Recorder);const abort=new AbortController(),ready=vi.fn();const result=new BrowserVoiceIO().capture(abort.signal,'',()=>{},ready);const rejected=expect(result).rejects.toMatchObject({name:'AbortError'});
 await settle();await vi.advanceTimersByTimeAsync(45000);expect(recordings).toBe(3);expect(ready).toHaveBeenCalledTimes(3);expect(fetch).not.toHaveBeenCalled();expect(stopTrack).toHaveBeenCalled();abort.abort();await rejected;
});

it('restores the actual system route when a previously selected output is cleared',async()=>{
 const {source,context}=audio();const setSinkId=vi.fn(async(_id:string)=>{});Object.assign(context,{setSinkId});const io=new BrowserVoiceIO();
 const first=io.speak('First',new AbortController().signal,'desk-speaker');await settle();source.onended?.();await first;
 const second=io.speak('Second',new AbortController().signal,'');await settle();source.onended?.();await second;expect(setSinkId.mock.calls).toEqual([['desk-speaker'],['']]);
});
