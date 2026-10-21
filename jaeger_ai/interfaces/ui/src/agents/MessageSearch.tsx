import { Dialog } from '@aether/ui';
import { useEffect, useRef, useState } from 'react';
import type { JaegerSource, MessageSearchPage, SavedMessageChunk } from '../api/source';
export function MessageSearch({ source, agentId, name, onClose }: { source: JaegerSource; agentId: string; name: string; onClose: () => void }) {
  const [query, setQuery] = useState(''), [page, setPage] = useState<MessageSearchPage>(), [error, setError] = useState<string>(), [loading, setLoading] = useState(false);
  const generation = useRef(0), loadingMore = useRef(false), readGeneration = useRef(0), readingLock = useRef(false);
  const [full,setFull]=useState<SavedMessageChunk>(),[reading,setReading]=useState(false);
  useEffect(() => {
    const owner = ++generation.current; readGeneration.current++;readingLock.current=false;setReading(false);setFull(undefined); setPage(undefined); setError(undefined); setLoading(Boolean(query.trim()));
    if (!query.trim() || !source.searchMessages) return;
    const timer = setTimeout(() => { void source.searchMessages!(agentId, query.trim()).then(result => {
      if (owner !== generation.current) return;
      if (result.agent_id !== agentId) throw Error('Search response belongs to another bot');
      setPage(result);
    }).catch(e => { if (owner === generation.current) setError(String(e)); }).finally(() => { if (owner === generation.current) setLoading(false); }); }, 200);
    return () => { generation.current++; readGeneration.current++; clearTimeout(timer); };
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
  const read = async (messageId:string, sessionId:string, offset:number, revision?:string) => {
    if(!source.savedMessage||readingLock.current)return;
    readingLock.current=true;setReading(true);setError(undefined);const owner=++readGeneration.current, searchOwner=generation.current;
    try{
      const result=await source.savedMessage(agentId,messageId,offset,revision);
      if(owner!==readGeneration.current||searchOwner!==generation.current)return;
      if(result.agent_id!==agentId||result.message_id!==messageId||result.session_id!==sessionId||result.offset!==offset||revision&&result.revision!==revision)throw Error('Saved message identity/revision mismatch');
      if(!Number.isSafeInteger(result.end_offset)||!Number.isSafeInteger(result.total_chars)||result.end_offset<offset||result.end_offset>result.total_chars||result.next_offset!==null&&(result.next_offset!==result.end_offset||result.next_offset<=offset)||result.previous_offset!==null&&(!Number.isSafeInteger(result.previous_offset)||result.previous_offset<0||result.previous_offset>=offset))throw Error('Saved message cursor did not advance');
      setFull(result);
    }catch(e){if(owner===readGeneration.current&&searchOwner===generation.current)setError(String(e));}
    finally{if(owner===readGeneration.current){readingLock.current=false;setReading(false);}}
  };
  return <Dialog open title={`Search messages with ${name}`} onClose={onClose} actions={<button type="button" onClick={onClose}>Close</button>}>
    <p>Literal text search across this bot's saved conversations, including older history. Your open chat and draft stay in place.</p>
    <label>Search messages<input aria-label="Search bot messages" value={query} maxLength={200} onChange={e => setQuery(e.target.value)} /></label>
    {loading && <p role="status">Searching saved messages…</p>}{error && <p role="alert">Could not search: {error}</p>}
    {page && !page.matches.length && <p>No matching saved messages.</p>}
    {page?.matches.map(hit => <details key={hit.message_id}><summary>{hit.role} · {new Date(hit.timestamp*1000).toLocaleString()} · {hit.snippet}</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{hit.content}</pre>{hit.truncated && <p>Preview is limited to 8,000 characters. The saved conversation retains the full message.</p>}{source.savedMessage&&<button type="button" disabled={reading} onClick={()=>void read(hit.message_id,hit.session_id,hit.match_offset??0,hit.content_revision)}>Open full saved message at match</button>}</details>)}
    {reading&&<p role="status">Reading saved message…</p>}
    {full?.agent_id===agentId&&<section aria-label="Full saved message"><h3>Saved {full.role} message</h3><p>Read-only · conversation {full.session_id} · characters {full.offset}–{full.end_offset} of {full.total_chars}. Your open chat, draft and unread state are unchanged.</p><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{full.content}</pre>{full.previous_offset!==null&&<button type="button" disabled={reading} onClick={()=>void read(full.message_id,full.session_id,full.previous_offset!,full.revision)}>Previous message portion</button>}{full.next_offset!==null&&<button type="button" disabled={reading} onClick={()=>void read(full.message_id,full.session_id,full.next_offset!,full.revision)}>Next message portion</button>}<button type="button" onClick={()=>{readGeneration.current++;readingLock.current=false;setReading(false);setFull(undefined);}}>Close saved message</button></section>}
    {page?.next_before && <button type="button" disabled={loading} onClick={() => void older()}>Show earlier matches</button>}
  </Dialog>;
}
