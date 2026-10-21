import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { SessionApprovals } from "./SessionApprovals";
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it("restores only this chat's pending handoff; decisions remain explicit and failed saves stay visible", async () => {
  const host = {
    pendingApprovals: vi.fn().mockResolvedValue([
      { approval_id: "own", session_id: "home", kind: "handoff", status: "pending", prompt: "Allow handoff to Beta?", task: "exact bounded task" },
      { approval_id: "foreign", session_id: "other", kind: "handoff", status: "pending", prompt: "foreign" },
      { approval_id: "tool", session_id: "home", kind: "tool", status: "pending", prompt: "other active turn" },
    ]),
    respondToConfirmation: vi.fn().mockRejectedValueOnce(new Error("Save rejected")).mockResolvedValue(undefined),
  };
  const el=document.createElement("div"); const root=createRoot(el);
  await act(async () => root.render(<SessionApprovals sessionId="home" host={host} excludeIds={["tool"]}/>));
  expect(el.textContent).toContain("Allow handoff to Beta?"); expect(el.textContent).toContain("exact bounded task");
  expect(el.textContent).not.toContain("foreign"); expect(host.respondToConfirmation).not.toHaveBeenCalled();
  const allow=()=>Array.from(el.querySelectorAll("button")).find(b=>b.textContent==="Allow once")!;
  await act(async () => allow().click());
  expect(el.textContent).toContain("Save rejected"); expect(el.textContent).toContain("Allow once");
  await act(async () => allow().click());
  expect(host.respondToConfirmation).toHaveBeenLastCalledWith("home","own","approve");
  expect(el.textContent).not.toContain("Allow once");
  await act(async () => root.unmount());
});

it("restores tool approval after reload without an active turn, and never decides it automatically", async () => {
 const host={pendingApprovals:vi.fn().mockResolvedValue([{approval_id:"restored-tool",session_id:"home",kind:"tool_confirm",status:"pending",prompt:"Allow fixture write?"}]),respondToConfirmation:vi.fn().mockResolvedValue(undefined)};
 const el=document.createElement('div');const root=createRoot(el);
 await act(async()=>root.render(<SessionApprovals sessionId="home" host={host}/>));
 expect(el.textContent).toContain('Allow fixture write?');expect(host.respondToConfirmation).not.toHaveBeenCalled();
 await act(async()=>Array.from(el.querySelectorAll('button')).find(b=>b.textContent?.startsWith('Deny once'))!.click());
 expect(host.respondToConfirmation).toHaveBeenCalledExactlyOnceWith('home','restored-tool','deny');
 expect(el.textContent).not.toContain('Allow fixture write?');await act(async()=>root.unmount());
});
