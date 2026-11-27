// The chat's record of a conversation, built from the agent's events. Copied from Omni's screen; Jaeger AI's server
// (gateway.py) sends: user (a run started, typed here or anywhere else), delta (reply text as the Gateway streams it),
// assistant (the whole reply), tool, state, status, done, reset (a new chat). Omni's audio/feeling still work.
// Pure functions, so the screen and its tests share them.

export type Tool = { name: string; detail?: string };
export type Message = { role: 'user' | 'assistant' | 'note'; text: string; tools: Tool[]; open: boolean; whole?: boolean; pics?: string[] };   // pics: pictures the person sent (data URLs)
export type Chat = { messages: Message[]; busy: boolean; status: string };
export type AgentEvent = { event?: string; text?: string; data?: unknown };

export const empty: Chat = { messages: [], busy: false, status: 'Ready' };

const last = (c: Chat) => c.messages[c.messages.length - 1];
const show = (data: unknown) => data === undefined || data === null ? undefined : typeof data === 'string' ? data : JSON.stringify(data);

/** The reply being written: the open assistant message, or a new one. */
function reply(c: Chat): [Chat, Message] {
  const m = last(c);
  if (m?.role === 'assistant' && m.open) return [c, m];
  const fresh: Message = { role: 'assistant', text: '', tools: [], open: true };
  return [{ ...c, messages: [...c.messages, fresh] }, fresh];
}

function change(c: Chat, m: Message, to: Partial<Message>): Chat {
  return { ...c, messages: c.messages.map(x => (x === m ? { ...m, ...to } : x)) };
}

/** The person typed a message and it was sent. */
export function sent(c: Chat, text: string, pics?: string[]): Chat {
  const m: Message = { role: 'user', text, tools: [], open: false, ...(pics?.length ? { pics } : {}) };
  return { messages: [...c.messages, m], busy: true, status: 'Thinking' };
}

export function onEvent(c: Chat, e: AgentEvent): Chat {
  const text = (e.text ?? '').trim();
  switch (e.event) {
    case 'user': {   // the microphone heard them; a typed line comes back as the same words, already shown
      const m = last(c);
      if (m?.role === 'user' && m.text === text) return { ...c, busy: true };
      return { ...sent(c, text), status: c.status };
    }
    case 'delta': {   // raw streamed text: appended exactly as it comes
      const d = e.text ?? '';
      if (!d) return c;
      const [n, m] = reply(c);
      return m.whole ? n : change(n, m, { text: m.text + d });
    }
    case 'reset':
      return empty;
    case 'audio': {
      if (!text) return c;
      const [n, m] = reply(c);
      if (m.whole) return n;   // Omni sends the whole reply first, then its sentences as they are voiced
      return change(n, m, { text: m.text ? `${m.text} ${text}` : text });
    }
    case 'assistant': {
      if (!text) return c;
      const [n, m] = reply(c);
      return change(n, m, { text, whole: true });
    }
    case 'tool':
    case 'feeling': {
      const [n, m] = reply(c);
      const tool = e.event === 'tool' ? { name: text || 'tool', detail: show(e.data) } : { name: 'feeling', detail: text };
      return change(n, m, { tools: [...m.tools, tool] });
    }
    case 'state':
      return text ? { ...c, status: text } : c;
    case 'status':
      return text.startsWith('error') ? { ...c, messages: [...c.messages, { role: 'note', text, tools: [], open: false }] } : c;
    case 'done': {
      const messages = c.messages
        .filter(m => !(m.role === 'assistant' && m.open && !m.text && !m.tools.length))
        .map(m => (m.open ? { ...m, open: false } : m));
      return { messages, busy: false, status: 'Ready' };
    }
    default:
      return c;
  }
}
