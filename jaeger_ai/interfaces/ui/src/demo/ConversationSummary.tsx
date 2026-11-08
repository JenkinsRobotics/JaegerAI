import { useEffect, useState } from 'react';
import type { JaegerSource, SessionFile } from '../api/source';
import type { Agent, Handoff } from '../api/types';
import { Bot, FileText, FolderOpen, Image, Plus, X } from '../components/Icons';
import { getJson } from '../unified/webui';
import type { WorkView } from './ConversationWorkPanel';

interface GitSnapshot { is_git: boolean; files?: { ignored?: boolean; additions?: number; deletions?: number }[]; truncated?: boolean }
/** A projection of the selected session, never counts from unrelated workers or workspaces. */
export function ConversationSummary({ source, sessionId, workspace, agents, onOpen, onClose }: {
  source: JaegerSource; sessionId: string; workspace?: string; agents: Agent[]; onOpen(view: WorkView): void; onClose(): void;
}) {
  const [files, setFiles] = useState<SessionFile[]>();
  const [handoffs, setHandoffs] = useState<Handoff[]>();
  const [git, setGit] = useState<GitSnapshot>();
  const [errors, setErrors] = useState<Record<string, string>>({});
  useEffect(() => {
    let live = true, loading = false;
    const refresh = async () => {
      if (!sessionId || loading) return;
      loading = true;
      const reads = [
        source.sessionFiles ? source.sessionFiles.list(sessionId).then(row => { if (row.session_id !== sessionId) throw Error('Source session mismatch'); return row.files; }) : Promise.reject(Error('Sources unavailable')),
        source.handoffs({ session_id: sessionId }).then(rows => rows.filter(row => row.session_id === sessionId)),
        source.kind === 'live' ? getJson<{ git: GitSnapshot }>(`/api/git/status?session_id=${encodeURIComponent(sessionId)}`).then(row => row.git) : Promise.reject(Error('No live workspace in this preview')),
      ] as const;
      const [sources, workers, changes] = await Promise.allSettled(reads);
      if (live) {
        const next: Record<string, string> = {};
        if (sources.status === 'fulfilled') setFiles(sources.value); else { setFiles(undefined); next.sources = 'Sources unavailable'; }
        if (workers.status === 'fulfilled') setHandoffs(workers.value); else { setHandoffs(undefined); next.workers = 'Subagents unavailable'; }
        if (changes.status === 'fulfilled') setGit(changes.value); else { setGit(undefined); next.git = 'Changes unavailable'; }
        setErrors(next);
      }
      loading = false;
    };
    void refresh(); const timer = setInterval(() => { if (!document.hidden) void refresh(); }, 15000);
    return () => { live = false; clearInterval(timer); };
  }, [source, sessionId]);
  const done = handoffs?.filter(row => ['done', 'completed', 'succeeded'].includes(row.status || '')).length || 0;
  const active = handoffs?.filter(row => ['running', 'queued', 'pending', 'working'].includes(row.status || '')).length || 0;
  const others = (handoffs?.length || 0) - done - active;
  const totals = git?.files?.filter(row => !row.ignored).reduce<{additions:number;deletions:number}>((sum, row) => ({ additions: sum.additions + (row.additions || 0), deletions: sum.deletions + (row.deletions || 0) }), { additions: 0, deletions: 0 });
  return <div id="jaeger-conversation-summary" className="jg-stable-demo__popover jg-conversation-summary" role="dialog" aria-label="Conversation summary">
    <header><h2>{workspace?.split(/[\\/]/).filter(Boolean).pop() || 'Conversation'}</h2><button type="button" aria-label="Close summary" onClick={onClose}><X size={18} /></button></header>
    <button className="jg-conversation-summary__changes" type="button" onClick={() => onOpen('changes')}><FileText size={20} /><span>Changes</span>{git?.is_git && totals ? <span className="jg-conversation-summary__counts" aria-label={`${totals.additions} additions, ${totals.deletions} deletions${git.truncated ? ', partial listing' : ''}`}><b>+{totals.additions}</b><b>−{totals.deletions}</b>{git.truncated && <small>partial</small>}</span> : <small>{!sessionId ? 'No conversation' : errors.git || (git ? 'No Git workspace' : 'Loading…')}</small>}</button>
    <section><h3>Subagents</h3><button type="button" onClick={() => onOpen('subagents')}><span className="jg-conversation-summary__avatars">{handoffs?.slice(0, 4).map(row => <span key={row.id} title={agents.find(agent => agent.id === row.to_agent_id)?.display_name || row.to_agent_id}><Bot size={18} /></span>)}</span><span>{!sessionId ? 'No conversation selected' : errors.workers || (!handoffs ? 'Loading…' : !handoffs.length ? 'No subagents in this conversation' : [done ? `${done} done` : '', active ? `${active} active` : '', others ? `${others} other` : ''].filter(Boolean).join(' · '))}</span></button></section>
    <section><header><h3>Sources</h3><button type="button" aria-label="Add sources" disabled={!sessionId || !source.uploadAttachment} onClick={() => onOpen('sources')}><Plus size={20} /></button></header>
      {files?.slice(0, 3).map(file => <button type="button" key={file.attachment_id} title={file.name} onClick={() => onOpen('sources')}>{file.mime.startsWith('image/') ? <Image size={20} /> : <FileText size={20} />}<span className="jg-conversation-summary__filename">{file.name}</span></button>)}
      {(!files || !files.length) && <p>{!sessionId ? 'Choose a conversation to see its sources.' : errors.sources || (files ? 'No sources added yet.' : 'Loading…')}</p>}
      <button type="button" className="jg-conversation-summary__view-all" disabled={!sessionId} onClick={() => onOpen('sources')}><FolderOpen size={20} />View all{files?.length ? ` (${files.length})` : ''}</button>
    </section>
  </div>;
}
