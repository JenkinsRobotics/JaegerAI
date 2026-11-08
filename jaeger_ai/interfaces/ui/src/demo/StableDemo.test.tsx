import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { MockSource } from "../api/mock";
import { StableDemo, DEMO_SESSION_KEY } from "./StableDemo";
vi.mock("../chat/ChatPane", () => ({ ChatPane: ({sessionId, onSessionMissing}: {sessionId: string; onSessionMissing?: (id: string) => void}) => <div data-chat-session={sessionId}>Real host mount point<button type="button" aria-label="Report missing session" onClick={() => onSessionMissing?.(sessionId)}>Report missing</button></div> }));
vi.mock("../windows/AppWindow", () => ({ AppWindow: ({embedded}: {embedded?: boolean}) => <div data-workspace-embedded={embedded}>Workspace page</div> }));
(globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
afterEach(async () => { await act(async () => root?.unmount()); localStorage.clear(); document.body.innerHTML = ""; history.replaceState(null, "", "/"); });
const flush = async (f: () => void = () => {}) => act(async () => {f();await new Promise(r=>setTimeout(r,0));});
it("closes the sidebar from its own control and with Escape", async () => {
 await mount();
 const shell = document.querySelector('.jg-stable-demo')!;
 const toggle = document.querySelector<HTMLButtonElement>('[aria-controls="jaeger-navigation"].jg-stable-demo__top-button')!;
 if (shell.getAttribute('data-sidebar') !== 'true') await flush(() => toggle.click());
 await flush(() => document.querySelector<HTMLButtonElement>('[aria-label="Close sidebar"]')!.click());
 expect(shell).toHaveAttribute('data-sidebar', 'false');
 await flush(() => toggle.click());
 expect(shell).toHaveAttribute('data-sidebar', 'true');
 await flush(() => document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'})));
 expect(shell).toHaveAttribute('data-sidebar', 'false');
});
it("does not present a new-chat welcome when history cannot be restored", async () => {
 const source = new MockSource();
 vi.spyOn(source, 'sessions').mockRejectedValue(new Error('Gateway unavailable'));
 await mount(source);
 expect(document.body.textContent).toContain('Waiting to reconnect');
 expect(document.body.textContent).not.toContain('What would you like to work on?');
});
async function mount(source = new MockSource()) {const el=document.createElement("div");document.body.append(el);root=createRoot(el);await flush(()=>root.render(<StableDemo source={source}/>));return source;}
it("keeps the shell in the visible viewport when the mobile keyboard opens", async () => {
 const viewport = Object.assign(new EventTarget(), {height:844,offsetTop:0,scale:1});
 const original = Object.getOwnPropertyDescriptor(window, 'visualViewport');
 Object.defineProperty(window, 'visualViewport', {configurable:true,value:viewport});
 const remove = vi.spyOn(viewport, 'removeEventListener');
 try {
  await mount();
  const shell = document.querySelector<HTMLElement>('.jg-stable-demo')!;
  expect(shell.style.getPropertyValue('--jg-viewport-height')).toBe('844px');
  await flush(() => {viewport.height=408;viewport.offsetTop=30;viewport.dispatchEvent(new Event('resize'));});
  expect(shell.style.getPropertyValue('--jg-viewport-height')).toBe('408px');
  expect(shell.style.getPropertyValue('--jg-viewport-top')).toBe('30px');
  await flush(() => {viewport.scale=2;viewport.dispatchEvent(new Event('resize'));});
  expect(shell.style.getPropertyValue('--jg-viewport-height')).toBe('');
  await flush(() => {viewport.scale=1;viewport.height=844;viewport.offsetTop=0;viewport.dispatchEvent(new Event('scroll'));});
  expect(shell.style.getPropertyValue('--jg-viewport-height')).toBe('844px');
  await flush(() => root.unmount());
  expect(remove.mock.calls.map(call=>call[0])).toEqual(['resize','scroll']);
 } finally {
  if(original)Object.defineProperty(window,'visualViewport',original);
  else delete (window as unknown as {visualViewport?: unknown}).visualViewport;
 }
});
it("offers one navigation for chat and every workspace page", async () => {
 await mount();expect([...document.querySelectorAll('#jaeger-navigation nav button')].map(e=>e.textContent)).toEqual(["Chat","Imagine","Library","Automations","Feed","Agents","Work","Research","Machine","Tasks"]);
 expect(document.body.textContent).not.toContain('Full workspace (preview)');
 expect(document.querySelector('[aria-label="Conversation toolbar"]')).toHaveClass('jg-stable-demo__header');
 expect(document.querySelector('.jg-stable-demo__profile-avatar')).not.toBeNull();
 expect(document.querySelector('[aria-label="Mobile navigation"]')).toBeNull();
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
it("opens the same most-recent durable conversation on a new live browser", async () => {
 const source = new MockSource();
 Object.defineProperty(source, 'kind', {value: 'live'});
 vi.spyOn(source, 'sessions').mockResolvedValue([
  {session_id: 'older', title: 'Older', agent_id: 'native:jaeger', last_activity_at: 10},
  {session_id: 'shared-latest', title: 'Shared latest', agent_id: 'native:jaeger', last_activity_at: 20},
 ]);
 vi.spyOn(source, 'session').mockResolvedValue({session_id: 'shared-latest'} as never);
 await mount(source);
 expect(document.querySelector('[data-chat-session]')?.getAttribute('data-chat-session')).toBe('shared-latest');
 expect(localStorage.getItem(DEMO_SESSION_KEY)).toBe('shared-latest');
});
it("recovers a phone whose saved conversation was deleted on another device", async () => {
 localStorage.setItem(DEMO_SESSION_KEY, 'deleted-on-mac');
 const source = new MockSource();
 Object.defineProperty(source, 'kind', {value: 'live'});
 vi.spyOn(source, 'sessions').mockResolvedValue([
  {session_id: 'shared-latest', title: 'Shared latest', agent_id: 'native:jaeger', last_activity_at: 20},
  {session_id: 'older', title: 'Older', agent_id: 'native:jaeger', last_activity_at: 10},
 ]);
 vi.spyOn(source, 'session').mockImplementation(async id => {
  if (id === 'deleted-on-mac') throw new Error('Session not found');
  return {session_id: id} as never;
 });
 await mount(source);
 await flush();
 expect(document.querySelector('[data-chat-session]')?.getAttribute('data-chat-session')).toBe('shared-latest');
 expect(localStorage.getItem(DEMO_SESSION_KEY)).toBe('shared-latest');
 expect(document.querySelector('[role=alert]')).toBeNull();
});
it("leaves a session that disappears while the chat is already mounted", async () => {
 localStorage.setItem(DEMO_SESSION_KEY, 'deleted-after-mount');
 const source = new MockSource();
 Object.defineProperty(source, 'kind', {value: 'live'});
 vi.spyOn(source, 'sessions').mockResolvedValue([
  {session_id: 'deleted-after-mount', title: 'Deleted elsewhere', agent_id: 'native:jaeger', last_activity_at: 30},
  {session_id: 'shared-fallback', title: 'Shared fallback', agent_id: 'native:jaeger', last_activity_at: 20},
 ]);
 vi.spyOn(source, 'session').mockImplementation(async id => ({session_id: id} as never));
 await mount(source);
 expect(document.querySelector('[data-chat-session]')?.getAttribute('data-chat-session')).toBe('deleted-after-mount');
 await flush(() => document.querySelector<HTMLButtonElement>('[aria-label="Report missing session"]')!.click());
 await vi.waitFor(() => expect(document.querySelector('[data-chat-session]')?.getAttribute('data-chat-session')).toBe('shared-fallback'));
 expect(localStorage.getItem(DEMO_SESSION_KEY)).toBe('shared-fallback');
 expect(document.body.textContent).not.toContain('Deleted elsewhere');
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
 expect(document.querySelector('[aria-label="Pinned workspace summary"]')?.textContent).toContain('Connection and activity');
 await flush(() => document.querySelector<HTMLButtonElement>('[aria-label="Open tabs"]')!.click());
 expect(document.querySelector('[aria-label="Open tabs menu"]')?.textContent).toContain('Working and shared tabs');
 expect(document.querySelector('[aria-label="Open tabs menu"]')?.textContent).toContain('No tabs are currently shared with Jaeger');
 expect(document.querySelector('[aria-label="Open tabs menu"]')?.textContent).not.toContain('Settings');
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
 expect(document.querySelector('.jg-stable-demo__profile')?.textContent).toContain('Jaeger');
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

it("organizes sessions into pinned, projects, and recents and permanently deletes a selected session", async () => {
 const source = new MockSource();
 vi.spyOn(source, "sessions").mockResolvedValue([
  {session_id:"project-chat",agent_id:"native:jaeger",title:"Project chat",workspace:"/Users/demo/JaegerAI"},
  {session_id:"recent-chat",agent_id:"native:jaeger",title:"Recent chat"},
 ]);
 const remove = vi.spyOn(source, "deleteSession");
 await mount(source);
 expect(document.querySelector(".jg-stable-demo__project")?.textContent).toContain("JaegerAI");
 expect(document.querySelector(".jg-stable-demo__project")?.textContent).toContain("Project chat");
 const pin = document.querySelector<HTMLButtonElement>('[aria-label="Pin Recent chat"]')!;
 await flush(() => pin.click());
 expect([...document.querySelectorAll(".jg-stable-demo__session-section")][0].textContent).toContain("Recent chat");
 await flush(() => [...document.querySelectorAll<HTMLButtonElement>("button")].find(button => button.textContent === "Manage")!.click());
 await flush(() => document.querySelector<HTMLInputElement>('[aria-label="Select Recent chat"]')!.click());
 await flush(() => [...document.querySelectorAll<HTMLButtonElement>("button")].find(button => button.textContent === "Delete selected")!.click());
 expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain("cannot be undone");
 await flush(() => [...document.querySelectorAll<HTMLButtonElement>("button")].find(button => button.textContent === "Delete permanently")!.click());
 expect(remove).toHaveBeenCalledWith("recent-chat");
 expect(document.body.textContent).not.toContain("Recent chat");
});

it("resizes the navigation with the accessible separator and remembers the width", async () => {
 await mount();
 const shell = document.querySelector<HTMLElement>(".jg-stable-demo")!;
 const separator = document.querySelector<HTMLElement>('[aria-label="Resize navigation"]')!;
 await flush(() => separator.dispatchEvent(new KeyboardEvent("keydown", {key:"End",bubbles:true})));
 expect(shell.style.getPropertyValue("--jg-stable-sidebar-width")).toBe("400px");
 expect(localStorage.getItem("jaeger.stable-demo.sidebar-width.v1")).toBe("400");
});

it("keeps the icon rail beside a context panel that changes with the selected tab", async () => {
 await mount();
 const rail=document.querySelector('.jg-stable-demo__rail')!;
 const context=document.querySelector('.jg-stable-demo__context')!;
 expect(rail.parentElement).toBe(context.parentElement);
 const choose=async (name:string)=>flush(()=>rail.querySelector<HTMLButtonElement>(`button[aria-label="${name}"]`)!.click());
 await choose('Library');
 expect(context.getAttribute('aria-label')).toBe('Library sidebar');
 expect(context.textContent).toContain('Documents');
 expect(context.textContent).not.toContain('New conversation');
 const documents=[...context.querySelectorAll('button')].find(button=>button.textContent==='Documents')!;
 await flush(()=>documents.click());
 expect(location.pathname+location.search).toBe('/library?section=documents');
 await choose('Agents');
 expect(context.textContent).toContain('Agent team');
 await choose('Chat');
 expect(context.textContent).toContain('New conversation');
 expect(document.querySelector('[aria-label="Mobile navigation"]')).toBeNull();
});
