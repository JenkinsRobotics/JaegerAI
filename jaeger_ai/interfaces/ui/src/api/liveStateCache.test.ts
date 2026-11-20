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
it.each(['/v1/sessions/s?view=control','/api/jaeger/gateway/health'])('never restores stale authority from the service-worker cache: %s', async () => {
  const listeners:Record<string,Function>={};
  const deleted:string[]=[];
  const caches={keys:vi.fn().mockResolvedValue(['jaeger-v0.13-stale']),delete:vi.fn(async (k:string)=>{deleted.push(k);return true;}),match:vi.fn(),open:vi.fn()};
  const clients={claim:vi.fn().mockResolvedValue(undefined)};
  runInNewContext(readFileSync('public/sw.js','utf8'),{self:{addEventListener:(name:string,fn:Function)=>{listeners[name]=fn},skipWaiting:vi.fn(),clients},URL,caches,console});
  // Push-only service worker deliberately installs NO fetch interceptor and purges legacy caches on activate.
  expect(listeners.fetch).toBeUndefined();
  let pending:Promise<unknown>|undefined;
  listeners.activate({waitUntil:(p:Promise<unknown>)=>{pending=p;}});
  await pending;
  expect(deleted).toEqual(['jaeger-v0.13-stale']);
  expect(clients.claim).toHaveBeenCalledOnce();
});
