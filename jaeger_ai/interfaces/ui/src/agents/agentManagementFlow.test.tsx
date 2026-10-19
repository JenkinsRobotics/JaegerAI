/** Full shared-UI action wiring with an explicit in-memory server fixture, not live acceptance. */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { App } from "../App";
import { MockSource } from "../api/mock";
import type { Agent } from "../api/types";
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
it("renames, archives, restores and pins the same agent through acknowledged backend actions", async () => {
  localStorage.clear();
  const worker: Agent = { id: "agent:worker", name: "worker", kind: "jaeger_native", role: "specialist", display_name: "Worker", archived: false, pinned: false, ui_actions: { read: true, rename: true, hide: true, pin: true } };
  const lead: Agent = { id: "native:jaeger", name: "jaeger", role: "lead", display_name: "Jaeger", ui_actions: { rename: true } };
  const source = new MockSource();
  vi.spyOn(source, "agents").mockImplementation(async () => [{ ...lead }, { ...worker }]);
  const patch = vi.fn(async (id: string, body: { display_name?: string | null; archived?: boolean }) => {
    expect(id).toBe(worker.id);
    if (body.display_name !== undefined) worker.display_name = body.display_name ?? "Worker";
    if (body.archived !== undefined) { worker.archived = body.archived; worker.hidden = body.archived; }
  });
  const savePins = vi.fn(async (ids: string[], expected: string[]) => { expect(expected).toEqual([]); worker.pinned = ids.includes(worker.id); worker.pin_order = 0; });
  Object.defineProperty(source, "agentActions", { value: { ...source.agentActions, patchAgent: patch, savePins } });
  const el = document.createElement("div"); document.body.append(el); const root = createRoot(el);
  const flush = async (fn: () => void) => { await act(async () => { fn(); await new Promise((resolve) => setTimeout(resolve, 0)); }); };
  const clickText = async (text: string) => flush(() => { [...el.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent!.replace(/[\uE000-\uF8FF]/g, "").trim() === text)!.click(); });
  const settings = async () => flush(() => { el.querySelector<HTMLButtonElement>('[aria-label^="Account"]')!.click(); });
  try {
    await flush(() => root.render(<App source={source} />));
    await settings(); await clickText("Agents");
    await flush(() => { [...el.querySelectorAll<HTMLElement>('[aria-label="Manage agents"] .jg-sheet__card')].find((r) => r.textContent!.includes(worker.id))!.querySelector<HTMLButtonElement>('button')!.click(); });
    await flush(() => {
      const input = el.querySelector<HTMLInputElement>('input[aria-label="Display name"]')!;
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'New worker label');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await clickText("Save display name");
    expect(patch).toHaveBeenCalledWith(worker.id, { display_name: "New worker label" });
    await settings();
    await clickText("Archive");
    expect(worker.archived).toBe(true);
    expect(el.querySelector('[data-agent-id="agent:worker"]')).toBeNull();
    await clickText("Restore");
    expect(worker.archived).toBe(false);
    await clickText("Pin");
    expect(savePins).toHaveBeenCalledWith([worker.id], []);
    expect(worker.id).toBe("agent:worker"); expect(worker.name).toBe("worker"); expect(worker.role).toBe("specialist");
  } finally { await flush(() => root.unmount()); el.remove(); localStorage.clear(); }
});
