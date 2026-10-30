/** Create a specialist and write its prompt through the specialist configuration (the field the gateway reads). */
import type { JaegerSource } from "../api/source";
import type { Agent } from "../api/types";
import { agentSlug } from "../agents/NewChatMenu";

const clean = (s: string | undefined, max: number) => (s ?? "").replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, "").slice(0, max);

export interface NewSpecialist { displayName: string; specialty: string; summary: string; instructions: string }

export async function createSpecialist(source: JaegerSource, spec: NewSpecialist): Promise<{ agent: Agent; configured: boolean }> {
  const agent = await source.createAgent({ operation_id: `agent-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`, name: agentSlug(spec.displayName), display_name: spec.displayName.trim(), role: "specialist", metadata: { specialty: clean(spec.specialty, 200) } });
  let configured = false;
  const controls = source.specialistControls;
  if (controls && (spec.instructions.trim() || spec.summary.trim() || spec.specialty.trim())) {
    try {
      const cur = await controls.read(agent.id);
      if (cur.editable) {
        await controls.save(agent.id, { expected_revision: cur.revision, settings: { specialty: clean(spec.specialty, 200), summary: clean(spec.summary, 2000), instructions: clean(spec.instructions, 12000) } });
        configured = true;
      }
    } catch { configured = false; }
  }
  return { agent, configured };
}
