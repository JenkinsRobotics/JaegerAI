import { act } from 'react'; import { createRoot } from 'react-dom/client'; import { it, expect, vi } from 'vitest';
import { DiagnosticsPanel } from './DiagnosticsPanel'; import type { JaegerSource } from '../api/source';
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
it('checks exact saved request and rejects a foreign receipt without a success label', async () => {
  const requestStatus = vi.fn(async () => ({ request_id: 'foreign', session_id: 'wrong-session', status: 'completed' }));
  const source = { diagnostics: async () => ({ sessions: 2, requests: { execution_unknown: 1 }, approvals: {}, handoffs: {}, unknown_requests: [{request_id:'owned-request',session_id:'owned-session',status:'execution_unknown'}], unknown_list_limit:20, process_id:123,server_module_sha256:'scoped-hash',fingerprint_scope:'module only',observed_at:1,read_only:true }), requestStatus } as unknown as JaegerSource;
  const element = document.createElement('div'); document.body.append(element); const root = createRoot(element);
  await act(async () => root.render(<DiagnosticsPanel source={source} />));
  await act(async () => { [...element.querySelectorAll('button')].find(b=>b.textContent==='Check saved request status')!.click(); });
  expect(requestStatus).toHaveBeenCalledExactlyOnceWith('owned-session','owned-request');
  expect(element.textContent).toContain('Request identity mismatch'); expect(element.textContent).not.toContain('Saved request owned-request: completed');
  await act(async () => root.unmount()); element.remove();
});
