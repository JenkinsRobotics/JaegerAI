import {MCPSetup} from './MCPSetup';
import {PluginCatalog} from './PluginCatalog';
import { MCPResources } from './MCPResources';
import { MCPControls } from './MCPControls';
import { useEffect, useState } from 'react';
import type { JaegerSource, ToolInventory } from '../api/source';
export function ToolsPanel({ source,sessionId }: { source: JaegerSource;sessionId?:string }) {
  const [resourceServer,setResourceServer]=useState<{id:string;name:string}>();
  const [query, setQuery] = useState(''), [attempt, setAttempt] = useState(0), [filter, setFilter] = useState('');
  const [snapshot, setSnapshot] = useState<ToolInventory>(), [error, setError] = useState<string>(), [loading, setLoading] = useState(false);
  useEffect(() => {
    let live = true; setLoading(true);
    const timer = setTimeout(() => { void source.tools?.(query).then(value => { if (live) { setSnapshot(value); setError(undefined); } }, e => { if (live) setError(String(e)); }).finally(() => { if (live) setLoading(false); }); }, 150);
    return () => { live = false; clearTimeout(timer); };
  }, [source, query, attempt]);
  return <section aria-label="Tools and MCP"><p>Tools already registered in this Gateway. Availability is not probed; execution still uses the current agent, request policy and approvals.</p>
    <label>Find tool <input aria-label="Find tool" value={query} maxLength={200} onChange={e => setQuery(e.target.value)} /></label>
    <label>Tool source <select aria-label="Tool source" value={filter} onChange={e => setFilter(e.target.value)}><option value="">All registered tools</option><option value="gateway">Gateway</option><option value="mcp">MCP</option></select></label>
    <button type="button" onClick={() => setAttempt(n => n + 1)}>Refresh registered inventory</button>
    {loading && <p role="status">Reading registered inventory…</p>}{error && <p role="alert">Could not read tools: {error}. Previous inventory retained.</p>}
    {snapshot && <><h3>MCP connections</h3>{!snapshot.mcp_initialized && <p>The Gateway MCP bridge is not initialized. No connection was attempted by this view.</p>}{snapshot.servers.map(server => <article key={server.id??server.name}><p>{server.name} · {server.state.replaceAll('_', ' ')} · {server.tool_count} registered tools · {server.active_calls??0} active calls</p>{server.id&&server.resources_advertised&&source.mcpResources&&server.state==='loaded_not_probed'&&<button type="button" onClick={()=>setResourceServer({id:server.id!,name:server.name})}>Inspect resources for {server.name}</button>}{server.id&&source.mcpControls&&<MCPControls controls={source.mcpControls} server={{...server,id:server.id}} refresh={()=>setAttempt(n=>n+1)}/>}</article>)}
      <h3>{snapshot.count} matching registered tools</h3>{snapshot.tools.filter(t => !filter || t.source === filter).map(tool => <article className="jg-card" key={tool.name}><strong>{tool.name}</strong><p>{tool.description}</p><p>{tool.server ?? 'Gateway'} · {tool.toolset || 'Unclassified'} · {tool.side_effect} · policy tier: {tool.permission_tier}{tool.beta ? ' · beta' : ''}{tool.dangerous ? ' · marked dangerous' : ''}</p><small>Availability not probed</small></article>)}</>}
    {source.mcpConfiguration&&<MCPSetup controls={source.mcpConfiguration}/>}
    {source.plugins&&<PluginCatalog controls={source.plugins} source={source} sessionId={sessionId}/>}
    {resourceServer&&source.mcpResources&&<MCPResources controls={source.mcpResources} server={resourceServer} onClose={()=>setResourceServer(undefined)}/>}
  </section>;
}
