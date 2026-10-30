/**
 * Characters (unified UI): the Apple UI's Character Library as "new agent from character".
 * Creating one calls the gateway's createAgent with the character's role and instructions,
 * then opens the new agent's chat.
 */
import { useState } from "react";
import type { JaegerSource } from "../api/source";
import { CharacterLibrary, type CharacterBio } from "../components/CharacterLibrary";
import { agentSlug } from "../agents/NewChatMenu";

export function characterAgentBody(c: CharacterBio, operationId: string) {
  return {
    operation_id: operationId,
    name: agentSlug(c.name),
    display_name: c.name,
    metadata: { specialty: c.role, description: c.description, character_id: c.id, voice_tone: c.voiceTone, instructions: c.customInstructions },
  };
}

export function CharactersPage({ source, refresh, onNavigate, characterId }: { characterId?: string | null; source: JaegerSource; refresh: () => Promise<void> | void; onNavigate: (to: string) => void }) {
  const [busy, setBusy] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const create = async (c: CharacterBio) => {
    if (busy) return;
    setBusy(c.id); setNotice(undefined);
    try {
      const agent = await source.createAgent(characterAgentBody(c, `character-${c.id}-${Date.now().toString(36)}`));
      await refresh();
      onNavigate(`/chat?agent=${encodeURIComponent(agent.id)}`);
    } catch (e) { setNotice(`Couldn't create ${c.name}: ${String((e as Error).message ?? e)}`); }
    finally { setBusy(undefined); }
  };
  return (
    <div className="jg-u-page jg-u-characters">
      {notice && <p className="jg-u-error" role="alert">{notice}</p>}
      {busy && <p className="jg-u-note" role="status">Creating agent…</p>}
      <CharacterLibrary initialCharacterId={characterId} onCreateAgent={(c) => void create(c)} />
    </div>
  );
}
