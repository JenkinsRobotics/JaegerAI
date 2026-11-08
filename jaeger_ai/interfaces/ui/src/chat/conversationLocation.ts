/** Conversation identity travels in links; drafts and navigation preferences stay device-local. */
export function validConversationId(id: string): boolean {
  return id.length > 0 && id.length <= 256 && !/[\x00-\x1f\x7f]/.test(id);
}

export function conversationPath(id: string, search = ''): string {
  if (!validConversationId(id)) throw Error('Invalid conversation ID');
  const previous = new URLSearchParams(search);
  const params = new URLSearchParams({session:id});
  // Native window chrome and an explicit development preview remain local to this client.
  for (const key of ['host','mock']) if (previous.has(key)) params.set(key, previous.get(key)!);
  return '/chat?' + params;
}

export function conversationLink(id: string, origin = location.origin): string {
  return new URL(conversationPath(id), origin).href;
}
