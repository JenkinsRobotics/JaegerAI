import { createServer } from 'node:http';
import type { AddressInfo } from 'node:net';
import { expect, it } from 'vitest';
import { GatewayClient } from './gateway';
import { parseSSEChunk } from './sse';
import { followTurn } from '../chat/followTurn';
import type { ChatPart } from '../chat/host';

// Real fetch/body decoding and request follower, against an owned faulting
// HTTP producer. This is transport integration, not live-provider acceptance.
for (const corruption of ['malformed', 'partial-eof', 'partial-proxy-error'] as const) {
  it(`replays a lost approval after ${corruption} without advancing past it`, async () => {
    const cursors: number[] = [];
    const requests: string[] = [];
    const frame = (id: number, event: string, payload: object) =>
      `id: ${id}\nevent: ${event}\ndata: ${JSON.stringify({ event_id: id, session_id: 's', data: { request_id: 'r', turn_id: 't', ...payload } })}\n\n`;
    const approval = frame(2, 'approval.request', { approval_id: 'a', tool: 'owned_tool', prompt: 'Approve owned tool?' });
    const server = createServer((req, res) => {
      requests.push(req.method!);
      const url = new URL(req.url!, 'http://localhost');
      const cursor = Number(url.searchParams.get('last_event_id') ?? 0);
      cursors.push(cursor);
      res.writeHead(200, { 'Content-Type': 'text/event-stream' });
      if (cursors.length === 1) {
        res.end(frame(1, 'turn.delta', { delta: 'Working' }) +
          (corruption === 'malformed' ? 'id: 2\nevent: approval.request\ndata: {"data":\n\n' :
            approval.slice(0, -10) + (corruption === 'partial-proxy-error' ? 'event: gateway.error\ndata: {"error":"upstream interrupted","source":"webui-proxy"}\n\n' : '')));
      } else {
        // Honor the client's cursor exactly as a retained Gateway stream does.
        res.end((cursor < 2 ? approval : '') + frame(3, 'turn.finish', {}));
      }
    });
    await new Promise<void>((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
    try {
      const parts: ChatPart[] = [];
      const client = new GatewayClient(`http://127.0.0.1:${(server.address() as AddressInfo).port}`);
      const result = await followTurn({
        source: { stream: client.stream.bind(client) }, sessionId: 's', requestId: 'r', turnId: 't', cursor: 0,
        signal: AbortSignal.timeout(3000), onPart: part => parts.push(part), backoffMs: [0], sleep: async () => {},
      });
      expect(result.state).toBe('complete');
      expect(parts.filter(part => part.kind === 'confirmation')).toEqual([
        // The replayed frame carries request r, but no tool-call identity.
        { kind: 'confirmation', callId: 'a', requestId: 'r', toolCallId: undefined, title: 'Run owned_tool?', message: 'Approve owned tool?' },
      ]);
      expect(cursors).toHaveLength(2);
      expect(cursors[1]).toBeLessThan(2);
      expect(requests).toEqual(['GET', 'GET']);
    } finally {
      server.closeAllConnections();
      await new Promise<void>(resolve => server.close(() => resolve()));
    }
  });
}

it('bounds persistent malformed-frame reconnects and leaves the request unknown without resending', async () => {
  const requests: string[] = [];
  const server = createServer((req, res) => {
    requests.push(`${req.method} ${req.url}`);
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    res.end('id: 9\nevent: turn.finish\ndata: {"private":\n\n');
  });
  await new Promise<void>((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  try {
    const parts: ChatPart[] = [];
    const client = new GatewayClient(`http://127.0.0.1:${(server.address() as AddressInfo).port}`);
    const result = await followTurn({
      source: { stream: client.stream.bind(client) }, sessionId: 's', requestId: 'r', cursor: 8,
      signal: AbortSignal.timeout(3000), onPart: part => parts.push(part), backoffMs: [0, 0], sleep: async () => {},
    });
    expect(result.state).toBe('unknown');
    expect(requests).toEqual(Array(3).fill('GET /v1/sessions/s/stream?last_event_id=8'));
    expect(JSON.stringify(parts)).not.toContain('private');
  } finally {
    server.closeAllConnections();
    await new Promise<void>(resolve => server.close(() => resolve()));
  }
});

// Both decoder users (session and global GatewayClient streams) use JSON wire
// envelopes. Still preserve legal JSON primitive payloads rather than narrowing
// the generic parser to object-only data.
it('continues to parse valid JSON string payloads', () => {
  expect(parseSSEChunk('id: 7\ndata: "owned text"\n\n').frames).toEqual([
    { id: '7', event: undefined, data: 'owned text' },
  ]);
});
