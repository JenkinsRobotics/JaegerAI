import {it,expect,vi,afterEach} from 'vitest';
import {parseSSEChunk} from './sse';import {GatewayClient} from './gateway';import {DIAGNOSTIC_CAPTURE_KEY} from './diagnosticCapture';
afterEach(()=>{vi.unstubAllGlobals();localStorage.clear();});
it('reports fixed parser category and a bounded numeric ID without frame contents',()=>{
 const observer=vi.fn();parseSSEChunk('id: 7\nevent: turn.delta\ndata: {PRIVATE-TOKEN\n\n',observer);
 expect(observer).toHaveBeenCalledExactlyOnceWith('malformed_json','7');expect(JSON.stringify(observer.mock.calls)).not.toContain('PRIVATE');
 const malicious=vi.fn();parseSSEChunk('id: PRIVATE-TOKEN\ndata: bad\n\n',malicious);expect(malicious).toHaveBeenCalledExactlyOnceWith('malformed_json',undefined);
});
it('keeps reporting off until opt-in and deduplicates same cause without transmitting data',async()=>{
 const client=new GatewayClient();const json=vi.spyOn(client,'json').mockResolvedValue({accepted:true});
 vi.stubGlobal('fetch',vi.fn(async()=>new Response('id: 7\nevent: turn.delta\ndata: {PRIVATE-FRAME\n\n',{status:200,headers:{'Content-Type':'text/event-stream'}})));
 await client.stream('owned-session',undefined,()=>{},new AbortController().signal);expect(json).not.toHaveBeenCalled();
 localStorage.setItem(DIAGNOSTIC_CAPTURE_KEY,JSON.stringify({id:'a'.repeat(32),expires_at:Date.now()/1000+60,boot_id:'owned'}));
 await client.stream('owned-session',undefined,()=>{},new AbortController().signal);
 await client.stream('owned-session',undefined,()=>{},new AbortController().signal);
 expect(json).toHaveBeenCalledTimes(2);
 const first=json.mock.calls[0][1] as Record<string,unknown>,second=json.mock.calls[1][1] as Record<string,unknown>;
 expect(first).toEqual({capture_id:'a'.repeat(32),event_id:expect.any(String),code:'malformed_json',session_id:'owned-session'});expect(first.event_id).toBe(second.event_id);expect(JSON.stringify(json.mock.calls)).not.toContain('PRIVATE');
});
it('counts subscriber failure without swallowing execution/reconnect behavior or logging error text',async()=>{
 localStorage.setItem(DIAGNOSTIC_CAPTURE_KEY,JSON.stringify({id:'a'.repeat(32),expires_at:Date.now()/1000+60,boot_id:'owned'}));
 const client=new GatewayClient();const json=vi.spyOn(client,'json').mockResolvedValue({});vi.stubGlobal('fetch',vi.fn(async()=>new Response('id: 8\nevent: turn.delta\ndata: {"delta":"PRIVATE-CONTENT"}\n\n')));
 await expect(client.stream('owned',undefined,()=>{throw Error('PRIVATE-ERROR');},new AbortController().signal)).rejects.toThrow('PRIVATE-ERROR');
 expect((json.mock.calls[0][1] as Record<string,unknown>).code).toBe('subscriber_error');expect(JSON.stringify(json.mock.calls)).not.toContain('PRIVATE');
});
