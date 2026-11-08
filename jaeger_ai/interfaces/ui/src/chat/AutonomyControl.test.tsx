import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import type { RuntimeAutonomySnapshot } from "../api/source";
import { AutonomyControl } from "./AutonomyControl";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const mounted: Array<() => void> = [];
afterEach(() => { while (mounted.length) mounted.pop()?.(); });

async function renderControl(host: Parameters<typeof AutonomyControl>[0]["host"]) {
  const element = document.createElement("div");
  document.body.append(element);
  const root = createRoot(element);
  await act(async () => root.render(<AutonomyControl host={host} />));
  mounted.push(() => { act(() => root.unmount()); element.remove(); });
  return element;
}

it("shows the three modes and changes the label only after the Gateway confirms", async () => {
  let resolve!: (value: RuntimeAutonomySnapshot) => void;
  const save = vi.fn(() => new Promise<RuntimeAutonomySnapshot>(done => { resolve = done; }));
  const element = await renderControl({
    runtimeAutonomy: vi.fn().mockResolvedValue({ autonomy: "ask", options: ["ask", "scoped", "auto"] }),
    setRuntimeAutonomy: save,
  });
  const trigger = element.querySelector<HTMLButtonElement>(".jg-composer__policy")!;
  expect(trigger.textContent).toContain("Ask for approval");
  await act(async () => trigger.click());
  expect(element.textContent).toContain("How should Jaeger actions be approved?");
  expect(element.textContent).toContain("Approve for me");
  expect(element.textContent).toContain("Full access");

  const scoped = [...element.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]')].find(button => button.textContent?.includes("Approve for me"))!;
  await act(async () => scoped.click());
  expect(save).toHaveBeenCalledExactlyOnceWith("scoped");
  expect(trigger.textContent).toContain("Ask for approval");
  await act(async () => resolve({ autonomy: "scoped", options: ["ask", "scoped", "auto"] }));
  expect(trigger.textContent).toContain("Approve for me");
  expect(element.querySelector('[role="menu"]')).toBeNull();
});

it("keeps the confirmed mode and exposes an error when the change fails", async () => {
  const element = await renderControl({
    runtimeAutonomy: vi.fn().mockResolvedValue({ autonomy: "scoped", options: ["ask", "scoped", "auto"] }),
    setRuntimeAutonomy: vi.fn().mockRejectedValue(new Error("Gateway refused the change")),
  });
  const trigger = element.querySelector<HTMLButtonElement>(".jg-composer__policy")!;
  expect(trigger.textContent).toContain("Approve for me");
  await act(async () => trigger.click());
  const automatic = [...element.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]')].find(button => button.textContent?.includes("Full access"))!;
  await act(async () => automatic.click());
  expect(trigger.textContent).toContain("Approve for me");
  expect(element.querySelector('[role="alert"]')?.textContent).toContain("Gateway refused the change");
  expect(element.querySelector('[role="menu"]')).not.toBeNull();
});

it('refreshes a mode changed on another device before selecting',async()=>{
 const read=vi.fn().mockResolvedValueOnce({autonomy:'ask'}).mockResolvedValue({autonomy:'scoped'});
 const element=await renderControl({runtimeAutonomy:read,setRuntimeAutonomy:vi.fn()});
 await act(async()=>element.querySelector<HTMLButtonElement>('.jg-composer__policy')!.click());
 expect(element.querySelector('.jg-composer__policy')?.textContent).toContain('Approve for me');
});
it('does not present a failed read as confirmed Ask mode',async()=>{
 const save=vi.fn();const element=await renderControl({runtimeAutonomy:vi.fn().mockRejectedValue(Error('offline')),setRuntimeAutonomy:save});
 expect(element.querySelector('.jg-composer__policy')?.textContent).toContain('unavailable');
 await act(async()=>element.querySelector<HTMLButtonElement>('.jg-composer__policy')!.click());
 expect(element.querySelector('[role="alert"]')?.textContent).toContain('Cannot verify');
 expect([...element.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]')].every(button=>button.disabled)).toBe(true);
 expect(save).not.toHaveBeenCalled();
});
