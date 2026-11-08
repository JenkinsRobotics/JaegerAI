import { expect, it, vi } from "vitest";
import { GatewayClient, GatewayError } from "./gateway";

it("loads, saves and clears the durable conversation boundary", async () => {
  const client = new GatewayClient();
  const snapshot = { unread: { request_id: 'request', role: 'user' as const }, event_id: 9 };
  const json = vi.spyOn(client, 'json').mockResolvedValue(snapshot);
  expect(await client.messageReadState.load('a/b')).toEqual(snapshot);
  expect(await client.messageReadState.save('a/b', snapshot.unread)).toEqual(snapshot);
  await client.messageReadState.clear('a/b');
  expect(json.mock.calls).toEqual([
    ['/v1/sessions/a%2Fb/read-state'],
    ['/v1/sessions/a%2Fb/read-state', snapshot.unread],
    ['/v1/sessions/a%2Fb/read-state', undefined, 'DELETE'],
  ]);
});

it("distinguishes an unsupported Gateway from a deleted conversation", async () => {
  const client = new GatewayClient();
  const json = vi.spyOn(client, 'json').mockRejectedValue(new GatewayError('404 Not Found', 404));
  await expect(client.messageReadState.load('s')).rejects.toThrow('unavailable on this Gateway version');
  json.mockRejectedValue(new GatewayError('Session not found', 404));
  await expect(client.messageReadState.load('s')).rejects.toThrow('Session not found');
});
