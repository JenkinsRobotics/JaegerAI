import { describe, expect, it, vi } from "vitest";
import { createSpecialist } from "./agentCreate";
import type { JaegerSource } from "../api/source";

describe("createSpecialist", () => {
  it("creates a specialist and saves instructions at the current revision", async () => {
    const createAgent = vi.fn().mockResolvedValue({ id: "a1", name: "ada" });
    const save = vi.fn().mockResolvedValue({});
    const source = { createAgent, specialistControls: { read: vi.fn().mockResolvedValue({ editable: true, revision: 2 }), save } } as unknown as JaegerSource;
    const r = await createSpecialist(source, { displayName: "Ada", specialty: "Data", summary: "", instructions: "Be exact" });
    expect(createAgent.mock.calls[0][0]).toMatchObject({ role: "specialist", display_name: "Ada" });
    expect(save).toHaveBeenCalledWith("a1", { expected_revision: 2, settings: { specialty: "Data", summary: "", instructions: "Be exact" } });
    expect(r.configured).toBe(true);
  });
  it("reports when the configuration can't be saved", async () => {
    const source = { createAgent: vi.fn().mockResolvedValue({ id: "a1" }), specialistControls: { read: vi.fn().mockRejectedValue(new Error("x")), save: vi.fn() } } as unknown as JaegerSource;
    expect((await createSpecialist(source, { displayName: "Ada", specialty: "", summary: "", instructions: "x" })).configured).toBe(false);
  });
});
