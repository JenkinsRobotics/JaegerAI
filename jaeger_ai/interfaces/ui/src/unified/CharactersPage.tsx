/**
 * Characters (unified UI): the Apple UI's Character Library as "new agent from character".
 * Creating one calls the gateway's createAgent as a "specialist", then writes the character's
 * role/description/instructions through the specialist configuration (the gateway reads the
 * prompt from operator_instructions, not from createAgent metadata), then opens the chat.
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
    role: "specialist",
    metadata: { specialty: c.role, description: c.description, character_id: c.id, voice_tone: c.voiceTone },
  };
}

// Mirrors the gateway's validate_settings limits; control codes (except tab/newline) are rejected there.
const clean = (s: string | undefined, max: number) => (s ?? "").replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, "").slice(0, max);
export function characterSettings(c: CharacterBio) {
  const instructions = [c.customInstructions, c.voiceTone ? `Voice and tone: ${c.voiceTone}` : ""].filter(Boolean).join("\n\n");
  return { specialty: clean(c.role, 200), summary: clean(c.description, 2000), instructions: clean(instructions, 12000) };
}

/** Writes the character prompt into the agent's specialist configuration. Returns false if the gateway won't let it be edited. */
export async function applyCharacter(source: JaegerSource, agentId: string, c: CharacterBio): Promise<boolean> {
  const controls = source.specialistControls;
  if (!controls) return false;
  const current = await controls.read(agentId);
  if (!current.editable) return false;
  await controls.save(agentId, { expected_revision: current.revision, settings: characterSettings(c) });
  return true;
}

export function CharactersPage({ source, refresh, onNavigate, characterId }: { characterId?: string | null; source: JaegerSource; refresh: () => Promise<void> | void; onNavigate: (to: string) => void }) {
  const [busy, setBusy] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const create = async (c: CharacterBio) => {
    if (busy) return;
    setBusy(c.id); setNotice(undefined);
    try {
      const agent = await source.createAgent(characterAgentBody(c, `character-${c.id}-${Date.now().toString(36)}`));
      let applied = false;
      try { applied = await applyCharacter(source, agent.id, c); } catch { applied = false; }
      await refresh();
      if (!applied) { setNotice(`${c.name} was created, but its character instructions couldn't be saved. Open the agent's Configuration to add them.`); return; }
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
