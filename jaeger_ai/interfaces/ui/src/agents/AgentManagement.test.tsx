import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { AgentManagement } from "./AgentManagement";
import { label, visible } from "./agentsLogic";
import type { Agent } from "../api/types";
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => { document.body.innerHTML = ""; });
it("keeps archived agents discoverable for restore and name reset, using immutable IDs", () => {
  const agent: Agent = { id: "agent:builder", name: "builder", role: "specialist", display_name: "Custom label", hidden: true, archived: true, pinned: true, presentation: { display_name: "Custom label" }, ui_actions: { rename: true, hide: true, pin: true } };
  const onArchive = vi.fn(), onRename = vi.fn(), onResetName = vi.fn(), onPin = vi.fn();
  const el = document.createElement("div"); document.body.append(el);
  const root = createRoot(el);
  act(() => root.render(<AgentManagement agents={[agent]} onArchive={onArchive} onRename={onRename} onResetName={onResetName} onPin={onPin} />));
  expect(visible(agent)).toBe(false);
  expect(el.textContent).toContain("agent:builder");
  const click = (text: string) => act(() => [...el.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent === text)!.click());
  click("Restore"); expect(onArchive).toHaveBeenCalledWith(agent, false);
  click("Rename"); expect(onRename).toHaveBeenCalledWith(agent);
  click("Reset display name"); expect(onResetName).toHaveBeenCalledWith(agent);
  click("Unpin"); expect(onPin).toHaveBeenCalledWith(agent, false);
  expect(agent.archived).toBe(true); // Only a successful server projection changes the roster.
  expect(visible({ ...agent, archived: false, hidden: false })).toBe(true);
  expect(label({ ...agent, role: "lead" })).toBe("Custom label");
  act(() => root.unmount());
});
