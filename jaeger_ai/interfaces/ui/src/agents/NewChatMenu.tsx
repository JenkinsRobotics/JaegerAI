/* The + button (Grok Bot "New chat"): a fresh chat with any agent, or a new
 * agent. A fresh chat never replaces an old one; both stay in the sidebar. */
import { Dialog, Menu, TextField, type MenuItem } from "@aether/ui";
import { useState } from "react";
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
  onCreateAgent: (displayName: string, job: string) => Promise<void>;
}

export function NewChatMenu({ anchor, agents, onClose, onNewChat, onCreateAgent }: Props) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [job, setJob] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  const closeDialog = () => { setCreating(false); setName(""); setJob(""); setError(undefined); };
  const submit = async () => {
    if (!agentSlug(name)) { setError("Give the agent a name."); return; }
    setBusy(true);
    try {
      await onCreateAgent(name.trim(), job.trim());
      closeDialog();
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
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
          <button type="button" className="aui-button aui-button--primary" disabled={busy} onClick={() => void submit()}>Create</button>
        </>}>
        <form className="jg-form" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
          <label className="jg-form__field">
            <span>Name</span>
            <TextField value={name} placeholder="Research" onChange={(e) => setName(e.target.value)} invalid={Boolean(error)} />
          </label>
          <label className="jg-form__field">
            <span>What should it do?</span>
            <TextField value={job} placeholder="Find and summarise sources for the lead" onChange={(e) => setJob(e.target.value)} />
          </label>
          {error && <p className="jg-form__error" role="alert">{error}</p>}
        </form>
      </Dialog>
    </>
  );
}
