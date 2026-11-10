import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { afterEach, expect, it, vi } from 'vitest';
import { httpGetJson } from '../chat/homeSession';
afterEach(() => vi.unstubAllGlobals());
it('reads restored home state from the server', async () => {
  const fetch = vi.fn().mockResolvedValue(Response.json({session_id:'s'}));
  vi.stubGlobal('fetch',fetch);
  await httpGetJson()('/v1/agents/native%3Ajaeger/home');
  expect(fetch).toHaveBeenCalledWith('/v1/agents/native%3Ajaeger/home', expect.objectContaining({cache:'no-store'}));
});
it.each(['/v1/sessions/s?view=control','/api/jaeger/gateway/health'])('never restores stale authority from the service-worker cache: %s', async path => {
  const listeners:Record<string,Function>={};
  const fetch=vi.fn().mockRejectedValue(new Error('offline'));
  const caches={match:vi.fn().mockResolvedValue(Response.json({status:'running'})),open:vi.fn()};
  runInNewContext(readFileSync('public/sw.js','utf8'),{self:{addEventListener:(name:string,fn:Function)=>{listeners[name]=fn}},URL,fetch,caches,console});
  let response:Promise<Response>|undefined;
  const request={method:'GET',url:'http://localhost'+path};
  listeners.fetch({request,respondWith:(result:Promise<Response>)=>{response=result}});
  await expect(response).rejects.toThrow('offline');
  expect(fetch).toHaveBeenCalledWith(request,{cache:'no-store'});
  expect(caches.match).not.toHaveBeenCalled();
  expect(caches.open).not.toHaveBeenCalled();
});
