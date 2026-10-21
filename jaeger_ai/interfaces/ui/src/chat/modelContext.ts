/** Content-free adapter dispatch observation; never evidence of provider consumption. */
export interface ModelContextOutline {
  shape: 'messages' | 'prompt' | 'unsupported';
  system_chars: number; tool_count: number; truncated: boolean;
  messages: { role: string; text_chars: number; omitted_blocks: number }[];
}
const count = (v: unknown) => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0 ? v : 0;
export function modelContext(value: unknown): ModelContextOutline {
  const p = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  return {shape: p.shape === 'messages' || p.shape === 'prompt' ? p.shape : 'unsupported',
    system_chars: count(p.system_chars), tool_count: count(p.tool_count), truncated: p.truncated === true,
    messages: Array.isArray(p.messages) ? p.messages.slice(0,2048).map(v => {
      const row = v && typeof v === 'object' ? v as Record<string, unknown> : {};
      return {role: typeof row.role === 'string' && ['system','developer','user','assistant','tool','function'].includes(row.role) ? row.role : 'other', text_chars: count(row.text_chars), omitted_blocks: count(row.omitted_blocks)};
    }) : []};
}
