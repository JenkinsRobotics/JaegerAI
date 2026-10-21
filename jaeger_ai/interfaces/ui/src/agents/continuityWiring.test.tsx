import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it, vi } from 'vitest';
import { HandoffReplyDialog } from './HandoffReplyDialog';
import { AgentAvatar } from './AgentAvatar';
import { GatewayClient } from '../api/gateway';
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
it('a failed follow-up send keeps the original intent and reconciles it by lookup; it is never resubmitted', async () => {
  localStorage.clear();
  const send = vi.fn().mockRejectedValueOnce(new Error('owned network failure'));
  let rid = '';
  const lookup = vi.fn(async (id: string, requestId: string) => ({ scope: 'handoff_reply', resource_id: id, request_id: requestId, outcome: 'saved',
    command: { task: 'owned follow-up', request_id: requestId }, handoff: { id: 'owned-child', status: 'pending_approval', task: 'owned follow-up', request_id: requestId, metadata: { reply_to_handoff_id: id } } }) as never);
  const el = document.createElement('div'); document.body.append(el); const root = createRoot(el);
  const flush = async (fn: () => void) => act(async () => { fn(); await new Promise((r) => setTimeout(r, 0)); });
  try {
    await flush(() => root.render(<HandoffReplyDialog handoffId="owned-parent" send={send} lookup={lookup} onClose={() => {}} />));
    const field = el.querySelector('textarea')!;
    await flush(() => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,'owned follow-up'); field.dispatchEvent(new Event('input',{bubbles:true})); });
    const submit = el.querySelector<HTMLButtonElement>('[type=submit]')!;
    await flush(() => submit.click());
    expect(field.value).toBe('owned follow-up'); expect(el.textContent).toContain('owned network failure'); expect(el.textContent).not.toContain('Awaiting approval.');
    expect(send).toHaveBeenCalledTimes(1); rid = send.mock.calls[0][2];
    expect(submit.disabled).toBe(true);
    await flush(() => submit.click());
    expect(send).toHaveBeenCalledTimes(1);
    const check = [...el.querySelectorAll('button')].find((b) => b.textContent === 'Check original follow-up')!;
    await flush(() => check.click());
    expect(lookup).toHaveBeenCalledWith('owned-parent', rid);
    expect(send).toHaveBeenCalledTimes(1);
    expect(el.textContent).toContain('Awaiting approval.'); expect(submit.disabled).toBe(true);
  } finally { await flush(() => root.unmount()); el.remove(); }
});
it('typed reply adapter sends correlation/idempotency to existing handoff proxy without tools or approval bypass fields', async () => {
  const client = new GatewayClient(); const json = vi.spyOn(client,'json').mockResolvedValue({id:'child',status:'pending_approval'});
  await client.replyHandoff('owned/parent','owned text','owned-request');
  expect(json).toHaveBeenCalledWith('/api/handoffs/owned%2Fparent/reply',{ task:'owned text',request_id:'owned-request' });
});
it('small preset remains the same identity while queued/waiting/error/history never claim running motion', () => {
  for (const state of ['idle','waiting','blocked','failed','spawning','finished'] as const) {
    const html = renderToStaticMarkup(<AgentAvatar id="native:owned" name="Alias" size={24} preset="robot-shield" state={state} primary />);
    expect(html).toContain('jg-avatar__robot'); expect(html).toContain('data-primary-agent-id="native:owned"'); expect(html).not.toContain('data-running="true"');
  }
  expect(renderToStaticMarkup(<AgentAvatar id="native:owned" name="Alias" preset="robot" state="working" />)).toContain('data-running="true"');
});
