/** Content-free adapter dispatch observation; never evidence of provider consumption. */
export interface ModelContextOutline {
  shape: 'messages' | 'prompt' | 'unsupported';
  system_chars: number; tool_count: number; truncated: boolean;
  items?: {reference:string;owner:string;record_ref:string;claim_id?:string;event_id?:string;document_id?:string;document_revision?:number;state:string}[];
  messages: { role: string; text_chars: number; omitted_blocks: number }[];
}
const count = (v: unknown) => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0 ? v : 0;
export function modelContext(value: unknown): ModelContextOutline {
  const p = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  const items = Array.isArray(p.items) ? p.items.slice(0,128).filter((v): v is Record<string,unknown> => Boolean(v && typeof v === 'object')).map(v=>({reference: typeof v.reference === 'string' && /^[a-f0-9]{32}$/.test(v.reference) ? v.reference : '', owner: ['semantic','episodic','reflection','skill','document'].includes(String(v.owner)) ? String(v.owner) : 'unknown', record_ref:typeof v.record_ref === 'string' && /^[a-f0-9]{64}$/.test(v.record_ref)?v.record_ref:'', state:['retained_exact','budget_dropped','not_retained_exact','unobservable'].includes(String(v.state))?String(v.state):'unobservable', ...(typeof v.claim_id === 'string' && /^clm_[a-f0-9]{12}$/.test(v.claim_id)?{claim_id:v.claim_id}:{}), ...(typeof v.event_id === 'string' && /^evt-[a-f0-9]{12}$/.test(v.event_id)?{event_id:v.event_id}:{}), ...(typeof v.document_id === 'string' && /^doc_[a-f0-9]{32}$/.test(v.document_id) && typeof v.document_revision === 'number' && Number.isSafeInteger(v.document_revision) && v.document_revision>0?{document_id:v.document_id,document_revision:v.document_revision}:{})})).filter(v=>v.reference && v.record_ref) : undefined;
  return {...(items ? {items} : {}),shape: p.shape === 'messages' || p.shape === 'prompt' ? p.shape : 'unsupported',
    system_chars: count(p.system_chars), tool_count: count(p.tool_count), truncated: p.truncated === true,
    messages: Array.isArray(p.messages) ? p.messages.slice(0,2048).map(v => {
      const row = v && typeof v === 'object' ? v as Record<string, unknown> : {};
      return {role: typeof row.role === 'string' && ['system','developer','user','assistant','tool','function'].includes(row.role) ? row.role : 'other', text_chars: count(row.text_chars), omitted_blocks: count(row.omitted_blocks)};
    }) : []};
}
