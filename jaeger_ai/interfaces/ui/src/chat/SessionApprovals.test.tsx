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

it("shows the full long multiline action after reload, with honest display limits", async () => {
 const action='command='+ 'x'.repeat(12000) + '\nSECOND_ACTION\ncwd=/synthetic/other-directory';
 const host={pendingApprovals:vi.fn().mockResolvedValue([{approval_id:"full",session_id:"home",kind:"tool_confirm",status:"pending",prompt:action}]),respondToConfirmation:vi.fn().mockResolvedValue(undefined)};
 const el=document.createElement('div');const root=createRoot(el);
 await act(async()=>root.render(<SessionApprovals sessionId="home" host={host}/>));
 expect(el.querySelector('pre')?.textContent).toBe(action);
 expect(el.querySelector('pre')?.getAttribute('aria-label')).toBe('Requested action');
 expect(el.textContent).toContain('Secret values may be redacted');
 expect(el.textContent).toContain('Older requests may contain only a summary');
 expect(host.respondToConfirmation).not.toHaveBeenCalled();
 await act(async()=>root.unmount());
});

it("offers no action while loading or when permission to read is refused", async () => {
 let refuse!: (error: Error) => void;
 const host={pendingApprovals:vi.fn().mockImplementation(()=>new Promise((_resolve,reject)=>{refuse=reject})),respondToConfirmation:vi.fn()};
 const el=document.createElement('div');const root=createRoot(el);
 await act(async()=>root.render(<SessionApprovals sessionId="home" host={host}/>));
 expect(el.querySelector('button')).toBeNull();
 await act(async()=>refuse(new Error('403 Forbidden')));
 expect(el.textContent).toContain('403 Forbidden');expect(el.querySelector('button')).toBeNull();
 expect(host.respondToConfirmation).not.toHaveBeenCalled();await act(async()=>root.unmount());
});

it("keeps the authoritative approval message visible beside a tool-event preview", async () => {
 const { ApprovalCard } = await import('./ApprovalCard');
 const prompt='Allow terminal.run_terminal? command="'+'x'.repeat(240)+'; SECOND_ACTION"\ncwd="/synthetic"';
 // Event and reload both use the broker's full prompt, not tool.started previews.
 const el=document.createElement('div');const root=createRoot(el);const decide=vi.fn();
 await act(async()=>root.render(<ApprovalCard title="Run terminal?" message={prompt} toolName="terminal" input={{command:'preview…'}} onDecide={decide}/>));
 expect(el.querySelector('pre[aria-label="Approval details"]')?.textContent).toBe(prompt);
 expect(el.querySelector('pre[aria-label="Approval details"]')?.className).toBe('jg-approval__cmd');
 expect(decide).not.toHaveBeenCalled();
 await act(async()=>root.unmount());
});
