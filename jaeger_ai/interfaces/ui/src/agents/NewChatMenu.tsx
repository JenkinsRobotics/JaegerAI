/* The + button (Grok Bot "New chat"): a fresh chat with any agent, or a new
 * agent. A fresh chat never replaces an old one; both stay in the sidebar. */
import { Dialog, TextField, type MenuItem } from "@aether/ui";
import { AppMenu as Menu } from "../popups/AppMenu";
import { useEffect, useRef, useState } from "react";
import type { AgentTemplate, SpecialistControls } from "../api/source";
import type { Agent } from "../api/types";
import { label } from "./agentsLogic";

const CREATE = "__create_agent__";

export function newChatItems(agents: Agent[]): MenuItem[] {
  return [
    ...agents.map((a) => ({ id: a.id, label: `New chat with ${label(a)}` })),
    { id: CREATE, label: "Create agent…", separatorBefore: agents.length > 0 },
  ];
}

/** Lowercase id-safe name for POST /v1/agents ("Research Lead" -> "research-lead"). */
export function agentSlug(display: string): string {
  return display.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
}

interface Props {
  anchor: HTMLElement | null;
  agents: Agent[];
  onClose: () => void;
  onNewChat: (agentId: string) => void;
  onCreateAgent: (displayName: string, job: string, operationId: string, template?: { id: string; version: number }, snapshot?:string) => Promise<void>;
  controls?: SpecialistControls;
  onRecoverAgent?: (operationId: string) => Promise<{ failed?: string }>;
}

export function NewChatMenu({ anchor, agents, onClose, onNewChat, onCreateAgent, onRecoverAgent, controls }: Props) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [job, setJob] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  const [snapshot,setSnapshot]=useState('');
  const [templates, setTemplates] = useState<AgentTemplate[]>([]), [templateId, setTemplateId] = useState("");
  const [templateError, setTemplateError] = useState<string>();
  useEffect(() => {
    if (!creating || !controls) return;
    let live = true;
    void controls.templates().then(v => { if (live) { setTemplates(v.templates); setTemplateError(v.unavailable_saved_sources?.length?'Some saved local template versions are unreadable; originals retained. Available templates remain usable.':undefined); } }, e => { if (live) setTemplateError(String(e)); });
    return () => { live = false; };
  }, [creating, controls]);
  const [pending, setPending] = useState<string>();
  const lock = useRef(false);
  const key = "jaeger.ui.agent-create.v1";
  useEffect(() => {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return;
      const value = JSON.parse(raw);
      if (typeof value.operationId !== "string" || typeof value.name !== "string" || typeof value.job !== "string") throw Error("Invalid saved creation command; original retained");
      setSnapshot(value.snapshot??''); setTemplateId(value.template?value.template.id+':v'+value.template.version:''); setPending(value.operationId); setName(value.name); setJob(value.job); setCreating(true);
    } catch (e) { lock.current = true; setCreating(true); setError(`Creation recovery unavailable: ${String(e)}`); }
  }, []);
  const closeDialog = () => { if (busy) return; setCreating(false); if (!pending) { setName(""); setJob(""); setSnapshot(''); setError(undefined); } };
  const submit = async () => {
    if (lock.current || pending) return;
    if (!agentSlug(name)) { setError("Give the agent a name."); return; }
    lock.current = true; setBusy(true); setError(undefined);
    const operationId = crypto.randomUUID();
    const selectedTemplate = templates.find(t => t.id+':v'+t.version === templateId);
    const template = selectedTemplate ? { id: selectedTemplate.id, version: selectedTemplate.version } : undefined;
    try {
      if (snapshot && templateId) throw Error("Choose a catalog template or a local snapshot, not both");
      if (snapshot) {const parsed=JSON.parse(snapshot);if(parsed?.format!=='jaeger.specialist-template')throw Error('Local template format unsupported');}
      if (templateId && !template) throw Error("Selected template is unavailable; reload the catalog before creating");
      localStorage.setItem(key, JSON.stringify({ operationId, name: name.trim(), job: job.trim(), template, snapshot:snapshot||undefined })); setPending(operationId);
      await onCreateAgent(name.trim(), job.trim(), operationId, template,snapshot||undefined);
      localStorage.removeItem(key); setPending(undefined); setCreating(false); setName(""); setJob(""); setSnapshot('');
    } catch (e) { setError(`Creation not confirmed: ${String((e as Error)?.message ?? e)}. Check saved creation; nothing is automatically retried.`); }
    finally { lock.current = false; setBusy(false); }
  };
  const recover = async () => {
    if (!pending || !onRecoverAgent || lock.current) return;
    lock.current = true; setBusy(true);
    try {
      const result = await onRecoverAgent(pending);
      localStorage.removeItem(key); setPending(undefined);
      if (result.failed) setError(result.failed); else { setCreating(false); setName(""); setJob(""); setSnapshot(''); setError(undefined); }
    } catch (e) { setError(String((e as Error)?.message ?? e)); }
    finally { lock.current = false; setBusy(false); }
  };

  return (
    <>
      <Menu open={Boolean(anchor)} anchor={anchor} items={newChatItems(agents)} ariaLabel="New chat" placement="bottom-end"
        onClose={onClose}
        onSelect={(id) => {
          onClose();
          if (id === CREATE) setCreating(true);
          else onNewChat(id);
        }} />
      <Dialog open={creating} title="Create agent" onClose={closeDialog}
        actions={<>
          <button type="button" className="aui-button" onClick={closeDialog}>Cancel</button>
          <button type="button" className="aui-button aui-button--primary" disabled={busy || Boolean(pending)} onClick={() => void submit()}>Create</button>
        </>}>
        <form className="jg-form" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
          {controls && <label className="jg-form__field"><span>Start from template</span><select aria-label="Agent template" disabled={busy || Boolean(pending)} value={templateId} onChange={e => setTemplateId(e.target.value)}><option value="">Blank specialist</option>{templates.map(t => <option key={t.id+':'+t.version} value={t.id+':v'+t.version}>{t.name} · v{t.version}</option>)}</select></label>}
          <label className="jg-form__field"><span>Local prompt template JSON (optional)</span><textarea aria-label="Local prompt template JSON" disabled={busy||Boolean(pending)} maxLength={100000} value={snapshot} onChange={e=>{setSnapshot(e.target.value);setTemplateId('');}}/></label>
          {snapshot&&<p>Creates a new specialist from the supplied prompt only. Source linkage is unverified; no history, accounts, plugin state or grants transfer. The server validates the exact policy and version.</p>}
          {templateError && <p role="alert">{templateError}. Blank creation remains available.</p>}
          {templateId && <p>{templates.find(t => t.id+':v'+t.version === templateId)?.summary} No tool permissions or credentials are copied.</p>}

          <label className="jg-form__field">
            <span>Name</span>
            <TextField disabled={busy || Boolean(pending)} value={name} placeholder="Research" onChange={(e) => setName(e.target.value)} invalid={Boolean(error)} />
          </label>
          <label className="jg-form__field">
            <span>What should it do?</span>
            <TextField disabled={busy || Boolean(pending)||Boolean(snapshot)} value={job} placeholder="Find and summarise sources for the lead" onChange={(e) => setJob(e.target.value)} />
          </label>
          {pending && <p role="status">Saved creation needs reconciliation. <button type="button" disabled={busy || !onRecoverAgent} onClick={() => void recover()}>Check saved creation</button></p>}
          {error && <p className="jg-form__error" role="alert">{error}</p>}
        </form>
      </Dialog>
    </>
  );
}
