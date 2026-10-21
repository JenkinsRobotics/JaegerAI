import { Dialog } from '@aether/ui';
import { useEffect, useRef, useState } from 'react';
import type { JaegerSource, MessageSearchPage } from '../api/source';
export function MessageSearch({ source, agentId, name, onClose }: { source: JaegerSource; agentId: string; name: string; onClose: () => void }) {
  const [query, setQuery] = useState(''), [page, setPage] = useState<MessageSearchPage>(), [error, setError] = useState<string>(), [loading, setLoading] = useState(false);
  const generation = useRef(0), loadingMore = useRef(false);
  useEffect(() => {
    const owner = ++generation.current; setPage(undefined); setError(undefined); setLoading(Boolean(query.trim()));
    if (!query.trim() || !source.searchMessages) return;
    const timer = setTimeout(() => { void source.searchMessages!(agentId, query.trim()).then(result => {
      if (owner !== generation.current) return;
      if (result.agent_id !== agentId) throw Error('Search response belongs to another bot');
      setPage(result);
    }).catch(e => { if (owner === generation.current) setError(String(e)); }).finally(() => { if (owner === generation.current) setLoading(false); }); }, 200);
    return () => { generation.current++; clearTimeout(timer); };
  }, [agentId, source, query]);
  const older = async () => {
    if (!page?.next_before || loadingMore.current || !source.searchMessages) return;
    loadingMore.current = true; setLoading(true); const owner = generation.current, before = page.next_before;
    try {
      const result = await source.searchMessages(agentId, query.trim(), before);
      if (owner !== generation.current) return;
      if (result.agent_id !== agentId || (result.next_before && Number(result.next_before) >= Number(before))) throw Error('Search cursor/identity did not advance');
      setPage(current => current && ({ ...result, matches: [...current.matches, ...result.matches.filter(hit => !current.matches.some(old => old.message_id === hit.message_id))] }));
    } catch (e) { if (owner === generation.current) setError(String(e)); }
    finally { loadingMore.current = false; if (owner === generation.current) setLoading(false); }
  };
  return <Dialog open title={`Search messages with ${name}`} onClose={onClose} actions={<button type="button" onClick={onClose}>Close</button>}>
    <p>Literal text search across this bot's saved conversations, including older history. Your open chat and draft stay in place.</p>
    <label>Search messages<input aria-label="Search bot messages" value={query} maxLength={200} onChange={e => setQuery(e.target.value)} /></label>
    {loading && <p role="status">Searching saved messages…</p>}{error && <p role="alert">Could not search: {error}</p>}
    {page && !page.matches.length && <p>No matching saved messages.</p>}
    {page?.matches.map(hit => <details key={hit.message_id}><summary>{hit.role} · {new Date(hit.timestamp*1000).toLocaleString()} · {hit.snippet}</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{hit.content}</pre>{hit.truncated && <p>Preview is limited to 8,000 characters. The saved conversation retains the full message.</p>}</details>)}
    {page?.next_before && <button type="button" disabled={loading} onClick={() => void older()}>Show earlier matches</button>}
  </Dialog>;
}
