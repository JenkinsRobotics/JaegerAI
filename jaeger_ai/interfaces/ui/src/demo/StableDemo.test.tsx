import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { MockSource } from "../api/mock";
import { StableDemo, DEMO_SESSION_KEY } from "./StableDemo";
vi.mock("../chat/ChatPane", () => ({ ChatPane: ({sessionId}: {sessionId: string}) => <div data-chat-session={sessionId}>Real host mount point</div> }));
vi.mock("../windows/AppWindow", () => ({ AppWindow: ({embedded}: {embedded?: boolean}) => <div data-workspace-embedded={embedded}>Workspace page</div> }));
(globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
afterEach(async () => { await act(async () => root?.unmount()); localStorage.clear(); document.body.innerHTML = ""; history.replaceState(null, "", "/"); });
const flush = async (f: () => void = () => {}) => act(async () => {f();await new Promise(r=>setTimeout(r,0));});
async function mount(source = new MockSource()) {const el=document.createElement("div");document.body.append(el);root=createRoot(el);await flush(()=>root.render(<StableDemo source={source}/>));return source;}
it("offers one navigation for chat and every workspace page", async () => {
 await mount();expect([...document.querySelectorAll('nav button')].map(e=>e.textContent)).toEqual(["Chat","Agents","Work","Tasks","Research","Studio","Machine"]);
 expect(document.body.textContent).not.toContain('Full workspace (preview)');
 expect(document.querySelectorAll('.jg-stable-demo__top-button')).toHaveLength(5);
 expect([...document.querySelectorAll<HTMLButtonElement>('.jg-stable-demo__tools > .jg-stable-demo__top-button')].map(button => button.getAttribute('aria-label'))).toEqual(["Conversation actions", "Toggle pinned summary", "Open tabs"]);
});
it("creates an isolated Jaeger session only after the user starts, then keeps chat mounted across task navigation", async () => {
 const source=new MockSource();const create=vi.spyOn(source,'createSession').mockResolvedValue({session_id:'demo-safe',agent_id:'native:jaeger'} as never);
 await mount(source);expect(create).not.toHaveBeenCalled();
 const start=[...document.querySelectorAll('button')].find(e=>e.textContent==='Start conversation')!;await flush(()=>start.click());
 expect(create).toHaveBeenCalledWith({agent_id:'native:jaeger',title:'Jaeger stable chat'});expect(localStorage.getItem(DEMO_SESSION_KEY)).toBe('demo-safe');
 const chat=document.querySelector('[data-chat-session]');await flush(()=>[...document.querySelectorAll('nav button')].find(e=>e.textContent==='Tasks')!.dispatchEvent(new MouseEvent('click',{bubbles:true})));
 expect(location.pathname).toBe('/work/tasks');
 expect(document.querySelector('[data-workspace-embedded="true"]')).not.toBeNull();
 expect(document.querySelector('[data-chat-session]')).toBe(chat);
});
it("retains a saved session and reports a connection failure without replacing it", async () => {
 localStorage.setItem(DEMO_SESSION_KEY,'existing-session');const source=new MockSource();vi.spyOn(source,'session').mockRejectedValue(new Error('Gateway unavailable'));const create=vi.spyOn(source,'createSession');await mount(source);
 expect(document.querySelector('[role=alert]')?.textContent).toContain('Gateway unavailable');expect(localStorage.getItem(DEMO_SESSION_KEY)).toBe('existing-session');expect(create).not.toHaveBeenCalled();
});

it("switches saved conversations without creating a session and keeps the selected chat usable", async () => {
 const source = new MockSource();
 vi.spyOn(source, 'sessions').mockResolvedValue([{session_id: 'saved', title: 'Saved work', agent_id: 'native:jaeger'}]);
 vi.spyOn(source, 'session').mockResolvedValue({session_id: 'saved'} as never);
 const create = vi.spyOn(source, 'createSession');
 await mount(source);
 const saved = [...document.querySelectorAll('button')].find(b => b.textContent === 'Saved work')!;
 await flush(() => saved.click());
 expect(document.querySelector('[data-chat-session]')?.getAttribute('data-chat-session')).toBe('saved');
 await flush(() => saved.click());
 expect(document.querySelector('[data-chat-session]')).not.toBeNull();
 expect(create).not.toHaveBeenCalled();
 expect(localStorage.getItem(DEMO_SESSION_KEY)).toBe('saved');
});
it("opens and closes the work panel without replacing the conversation", async () => {
 await mount();
 const summary = document.querySelector<HTMLButtonElement>('[aria-label="Toggle pinned summary"]')!;
 await flush(() => summary.click());
 await flush(() => [...document.querySelectorAll('button')].find(b => b.textContent === 'Files and changes')!.click());
 await flush(() => [...document.querySelectorAll('button')].find(b => b.textContent === 'Files & changes')!.click());
 expect(document.querySelector('#jaeger-work-panel')?.textContent).toContain('Start a conversation');
 await flush(() => document.querySelector<HTMLButtonElement>('[aria-label="Close work panel"]')!.click());
 expect(document.querySelector('#jaeger-work-panel')).toBeNull();
 expect(summary.getAttribute('aria-expanded')).toBe('false');
});

it("opens the three Codex-style header popovers with real Jaeger destinations", async () => {
 await mount();
 const actions = document.querySelector<HTMLButtonElement>('[aria-label="Conversation actions"]')!;
 await flush(() => actions.click());
 expect(document.querySelector('[aria-label="Conversation actions menu"]')?.textContent).toContain('Rename');
 expect(document.querySelector('[aria-label="Conversation actions menu"]')?.textContent).toContain('Open in new window');
 await flush(() => document.querySelector<HTMLButtonElement>('[aria-label="Toggle pinned summary"]')!.click());
 expect(document.querySelector('[aria-label="Pinned workspace summary"]')?.textContent).toContain('Environment');
 expect(document.querySelector('[aria-label="Pinned workspace summary"]')?.textContent).toContain('Background processes');
 await flush(() => document.querySelector<HTMLButtonElement>('[aria-label="Open tabs"]')!.click());
 expect(document.querySelector('[aria-label="Open tabs menu"]')?.textContent).toContain('Tasks · Work · Jaeger');
});

it("collapses each column independently without remounting the chat", async () => {
 localStorage.setItem(DEMO_SESSION_KEY, 'saved');
 const source = new MockSource();
 vi.spyOn(source, 'session').mockResolvedValue({session_id: 'saved'} as never);
 await mount(source);
 const chat = document.querySelector('[data-chat-session]');
 const toggle = document.querySelector<HTMLButtonElement>('[aria-label="Toggle navigation"]')!;
 await flush(() => toggle.click());
 expect(document.querySelector<HTMLElement>('#jaeger-navigation')?.hidden).toBe(true);
 expect(toggle.getAttribute('aria-expanded')).toBe('false');
 expect(document.querySelector('[data-chat-session]')).toBe(chat);
 await flush(() => toggle.click());
 expect(document.querySelector<HTMLElement>('#jaeger-navigation')?.hidden).toBe(false);
 expect(document.querySelector('[data-chat-session]')).toBe(chat);
 expect(document.querySelector('.jg-stable-demo__identity')?.textContent).toContain('Jaeger');
});
it("opens searchable draft settings and returns to the same chat", async () => {
 localStorage.setItem(DEMO_SESSION_KEY, 'saved');
 const source = new MockSource();
 vi.spyOn(source, 'session').mockResolvedValue({session_id: 'saved'} as never);
 await mount(source);
 const chat = document.querySelector('[data-chat-session]');
 await flush(() => { const settings = [...document.querySelectorAll('button')].find(button => button.textContent === 'Settings')!; settings.focus(); settings.click(); });
 expect(document.querySelector('#jaeger-settings-title')?.textContent).toBe('General');
 const nav = document.querySelector('[aria-label="Settings categories"]')!;
 expect(nav.querySelectorAll('button')).toHaveLength(23);
 await flush(() => [...nav.querySelectorAll('button')].find(button => button.textContent === 'Worktrees')!.click());
 expect(document.querySelector('#jaeger-settings-title')?.textContent).toBe('Worktrees');
 await flush(() => document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'})));
 expect(document.querySelector('[aria-label="Settings navigation"]')).toBeNull();
 expect(document.querySelector('[data-chat-session]')).toBe(chat);
 expect(document.activeElement?.textContent).toBe('Settings');
});
