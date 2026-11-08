import { afterEach, expect, it, vi } from 'vitest';
import { NativeVoiceIO } from './nativeVoiceIO';
afterEach(()=>{delete window.jaegerNative;vi.restoreAllMocks();});
const event=(detail:unknown)=>window.dispatchEvent(new CustomEvent('jaeger:native',{detail}));
it('sends native mic audio through the existing bridge and waits for its final transcript',async()=>{
 const post=vi.fn(async()=>({}));window.jaegerNative={post};let stop!:()=>void;const level=vi.fn();
 const result=new NativeVoiceIO().capture(new AbortController().signal,'',level,value=>{stop=value;});await Promise.resolve();
 expect(post).toHaveBeenCalledWith('mic.start',{mode:'dictation'});stop();expect(post).toHaveBeenCalledWith('mic.stop');
 event({type:'voice.transcript',text:'Hello Jaeger',final:true});expect(await result).toBe('Hello Jaeger');expect(level).toHaveBeenLastCalledWith(0);
});
it('aborts only its own native capture and ignores late transcription',async()=>{
 const post=vi.fn(async()=>({}));window.jaegerNative={post};const abort=new AbortController();
 const result=new NativeVoiceIO().capture(abort.signal,'',()=>{},()=>{});const rejected=expect(result).rejects.toMatchObject({name:'AbortError'});await Promise.resolve();abort.abort();await rejected;
 expect(post).toHaveBeenCalledWith('mic.stop');event({type:'voice.transcript',text:'late',final:true});
});
it('awaits actual native playback completion',async()=>{
 const post=vi.fn(async()=>({}));window.jaegerNative={post};let ended=false;
 const result=new NativeVoiceIO().speak('Hello',new AbortController().signal,'').then(()=>{ended=true;});await Promise.resolve();expect(ended).toBe(false);expect(post).toHaveBeenCalledWith('tts.speak',{text:'Hello'});
 event({type:'tts.done',completed:true});await result;expect(ended).toBe(true);
});
