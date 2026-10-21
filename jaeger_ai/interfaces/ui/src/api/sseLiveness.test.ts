import { afterEach, expect, it, vi } from 'vitest';
import { decodeSSE } from './sse';
afterEach(()=>vi.useRealTimers());
it('retires an idle reader without fabricating a frame or changing request identity',async()=>{
 vi.useFakeTimers();let cancelled=false;
 const body=new ReadableStream<Uint8Array>({cancel(){cancelled=true;}});
 const next=decodeSSE(body,undefined,30).next();const assertion=expect(next).rejects.toThrow('transport idle');
 await vi.advanceTimersByTimeAsync(31);await assertion;expect(cancelled).toBe(true);
});
it('keepalive bytes reset transport timeout but never become model progress',async()=>{
 vi.useFakeTimers();let controller!:ReadableStreamDefaultController<Uint8Array>;
 const body=new ReadableStream<Uint8Array>({start(c){controller=c;}});
 const iterator=decodeSSE(body,undefined,30);const next=iterator.next();const encoder=new TextEncoder();
 await vi.advanceTimersByTimeAsync(20);controller.enqueue(encoder.encode(': keepalive\n\n'));
 await vi.advanceTimersByTimeAsync(20);controller.enqueue(encoder.encode(': keepalive\n\n'));
 await vi.advanceTimersByTimeAsync(20);controller.enqueue(encoder.encode('id: 1\nevent: turn.delta\ndata: {"delta":"real token"}\n\n'));
 expect((await next).value).toMatchObject({id:'1',event:'turn.delta',data:{delta:'real token'}});await iterator.return(undefined);
});
