import { useState } from "react";
import type { Agent } from "../api/types";
import { label } from "./agentsLogic";
import { useExclusivePopup } from "../popups/coordinator";

export function PrimaryPicker({ agents, busy, onPick, onClose }: {
  agents: Agent[]; busy: boolean; onPick: (id: string) => void; onClose: () => void;
}) {
  const [chosen, setChosen] = useState("");
  useExclusivePopup(true, onClose);
  return <div className="jg-amenu__scrim" onMouseDown={onClose}>
    <form className="jg-aprompt" role="dialog" aria-label="Choose a primary Bot" onMouseDown={(e) => e.stopPropagation()}
      onSubmit={(e) => { e.preventDefault(); if (chosen && !busy) onPick(chosen); }}>
      <h3>Choose a primary Bot</h3>
      <p>Choose an existing agent. Its role, permissions, context and conversations stay unchanged. Your open chat stays open.</p>
      <select aria-label="Primary bot candidate" value={chosen} onChange={(e) => setChosen(e.target.value)}>
        <option value="">Select a bot</option>
        {agents.map((a) => <option key={a.id} value={a.id}>{label(a)}</option>)}
      </select>
      {!agents.length && <p>No eligible alternatives. Restore a hidden bot in Settings first.</p>}
      <div className="jg-aprompt__actions"><button type="button" onClick={onClose} disabled={busy}>Cancel</button>
        <button type="submit" className="is-primary" disabled={!chosen || busy}>Make primary</button></div>
    </form>
  </div>;
}
