import { describe, expect, it, vi } from "vitest";
import { applyCharacter, characterAgentBody, characterSettings } from "./CharactersPage";
import type { JaegerSource } from "../api/source";

const bio = { id: "c1", name: "Ada Bot", role: "Analyst", description: "Reads data", voiceTone: "Calm", customInstructions: "Be precise.\u0007" } as never;

describe("character agents", () => {
  it("creates as a specialist without relying on ignored metadata.instructions", () => {
    const body = characterAgentBody(bio, "op");
    expect(body.role).toBe("specialist");
    expect(body.metadata).not.toHaveProperty("instructions");
  });
  it("maps the character into specialist settings within gateway limits", () => {
    expect(characterSettings(bio)).toEqual({ specialty: "Analyst", summary: "Reads data", instructions: "Be precise.\n\nVoice and tone: Calm" });
  });
  it("saves instructions at the current revision", async () => {
    const save = vi.fn().mockResolvedValue({});
    const source = { specialistControls: { read: vi.fn().mockResolvedValue({ editable: true, revision: 3 }), save } } as unknown as JaegerSource;
    expect(await applyCharacter(source, "a1", bio)).toBe(true);
    expect(save).toHaveBeenCalledWith("a1", { expected_revision: 3, settings: characterSettings(bio) });
  });
  it("reports non-editable agents", async () => {
    const source = { specialistControls: { read: vi.fn().mockResolvedValue({ editable: false, revision: 1 }), save: vi.fn() } } as unknown as JaegerSource;
    expect(await applyCharacter(source, "a1", bio)).toBe(false);
  });
});
