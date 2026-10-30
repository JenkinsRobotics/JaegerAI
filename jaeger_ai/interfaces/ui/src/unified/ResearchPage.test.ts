import { expect, it } from "vitest";
import { isResearch, researchGoal } from "./ResearchPage";

it("builds a multi-step research goal the page can recognise", () => {
  const g = researchGoal("  MLX vs GGUF? ", "deep");
  expect(g.startsWith("Deep research: MLX vs GGUF?\n")).toBe(true);
  expect(g).toContain("up to 8 sub-questions");
  expect(isResearch({ task_id: "t", goal: g })).toBe(true);
  expect(isResearch({ task_id: "t", goal: "Write code" })).toBe(false);
});
