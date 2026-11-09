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
it("toggles the sidebar from the top bar and closes with Escape", async () => {
 await mount();
 const shell = document.querySelector('.jg-stable-demo')!;
 const toggle = document.querySelector<HTMLButtonElement>('[aria-controls="jaeger-navigation"].jg-stable-demo__top-button')!;
 if (shell.getAttribute('data-sidebar') !== 'true') await flush(() => toggle.click());
 await flush(() => toggle.click());
 expect(shell).toHaveAttribute('data-sidebar', 'false');
 expect(document.querySelector('#jaeger-navigation')).not.toHaveAttribute('hidden');
 expect(document.querySelector('#jaeger-navigation-context')).toHaveAttribute('hidden');
 expect(toggle).toHaveAttribute('aria-expanded', 'false');
 expect(document.querySelector('.jg-stable-demo__rail [aria-controls="jaeger-navigation-context"]')).toBeNull();
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
it('opens an explicit conversation link before any device-local or most-recent choice',async()=>{
 history.replaceState(null,'','/chat?session=from-ide');localStorage.setItem(DEMO_SESSION_KEY,'phone-old');
 const source=new MockSource();Object.defineProperty(source,'kind',{value:'live'});
 vi.spyOn(source,'sessions').mockResolvedValue([{session_id:'latest-other',title:'Other',agent_id:'native:jaeger'}]);
 const load=vi.spyOn(source,'session').mockImplementation(async id=>({session_id:id,title:'Shared from IDE',agent_id:'native:jaeger'}));
 const create=vi.spyOn(source,'createSession');await mount(source);
 expect(load).toHaveBeenCalledWith('from-ide');expect(load).not.toHaveBeenCalledWith('phone-old');
 expect(document.querySelector('[data-chat-session]')).toHaveAttribute('data-chat-session','from-ide');
 expect(create).not.toHaveBeenCalled();
});
it('preserves an unavailable explicit link without attaching another chat',async()=>{
 history.replaceState(null,'','/chat?session=missing');
 const source=new MockSource();Object.defineProperty(source,'kind',{value:'live'});
 vi.spyOn(source,'sessions').mockResolvedValue([{session_id:'other',title:'Other',agent_id:'native:jaeger'}]);
 const load=vi.spyOn(source,'session').mockRejectedValue(new Error('Session not found'));
 await mount(source);
 expect(document.querySelector('[data-chat-session]')).toBeNull();
 expect(load.mock.calls.every(call=>call[0]==='missing')).toBe(true);
 expect(location.search).toBe('?session=missing');
 expect(document.body.textContent).toContain('no other conversation was opened');
});
it('uses the Gateway-selected conversation on a fresh device without overriding other windows',async()=>{
 const source=new MockSource();Object.defineProperty(source,'kind',{value:'live'});
 vi.spyOn(source,'sessions').mockResolvedValue([{session_id:'latest',last_activity_at:20},{session_id:'chosen',last_activity_at:10}]);
 vi.spyOn(source,'session').mockImplementation(async id=>({session_id:id}));
 Object.assign(source,{operatorSession:vi.fn().mockResolvedValue({active_session_id:'chosen',revision:4})});
 await mount(source);await flush();
 expect(document.querySelector('[data-chat-session]')).toHaveAttribute('data-chat-session','chosen');
 expect(location.search).toBe('?session=chosen');
});
it('resolves browser back and forward conversation identities without starting new work',async()=>{
 history.replaceState(null,'','/chat?session=first');
 const source=new MockSource();vi.spyOn(source,'session').mockImplementation(async id=>({session_id:id}));
 const create=vi.spyOn(source,'createSession');await mount(source);
 await flush(()=>{history.pushState(null,'','/chat?session=second');dispatchEvent(new PopStateEvent('popstate'));});await flush();
 expect(document.querySelector('[data-chat-session]')).toHaveAttribute('data-chat-session','second');
 expect(create).not.toHaveBeenCalled();
});
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
  expect(shell.dataset.keyboard).toBe('true');
  await flush(() => {viewport.scale=2;viewport.dispatchEvent(new Event('resize'));});
  expect(shell.style.getPropertyValue('--jg-viewport-height')).toBe('');
  expect(shell.dataset.keyboard).toBeUndefined();
  await flush(() => {viewport.scale=1;viewport.height=844;viewport.offsetTop=0;viewport.dispatchEvent(new Event('scroll'));});
  expect(shell.style.getPropertyValue('--jg-viewport-height')).toBe('844px');
  expect(shell.dataset.keyboard).toBe('false');
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
 expect([...document.querySelectorAll<HTMLButtonElement>('.jg-stable-demo__tools > .jg-stable-demo__top-button')].map(button => button.getAttribute('aria-label'))).toEqual(["Conversation actions", "Conversation summary", "Toggle tools workspace"]);
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
it("keeps a disappeared conversation's exact address until the operator chooses another", async () => {
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
 expect(document.querySelector('[data-chat-session]')).toBeNull();
 expect(location.search).toBe('?session=deleted-after-mount');
 expect(document.body.textContent).toContain('no other conversation was opened');
 expect(document.body.textContent).not.toContain('Deleted elsewhere');
 await flush(()=>[...document.querySelectorAll('button')].find(button=>button.textContent==='Shared fallback')!.click());
 expect(document.querySelector('[data-chat-session]')).toHaveAttribute('data-chat-session','shared-fallback');
});
it("opens tools independently from its compact summary and preserves the conversation", async () => {
 localStorage.setItem(DEMO_SESSION_KEY, 'saved');
 const source = new MockSource();vi.spyOn(source,'session').mockResolvedValue({session_id:'saved'});
 await mount(source);
 const chat=document.querySelector('[data-chat-session]');
 const toggle=document.querySelector<HTMLButtonElement>('[aria-label="Toggle tools workspace"]')!;
 await flush(()=>toggle.click());
 expect(document.querySelector('[aria-label="Tools workspace"]')).not.toBeNull();
 expect(document.querySelector('[role="tabpanel"]')?.textContent).toContain('Suggested');
 await flush(()=>document.querySelector<HTMLButtonElement>('[aria-label="Conversation summary"]')!.click());
 expect(document.querySelector('[aria-label="Conversation summary"][role="dialog"]')?.textContent).toContain('Subagents');
 expect(document.querySelector('[aria-label="Conversation summary"][role="dialog"]')?.textContent).toContain('Sources');
 expect(document.querySelector<HTMLElement>('#jaeger-work-panel')?.hidden).toBe(false);
 await flush(()=>document.querySelector<HTMLButtonElement>('[aria-label="Close summary"]')!.click());
 await flush(()=>toggle.click());
 expect(document.querySelector<HTMLElement>('#jaeger-work-panel')?.hidden).toBe(true);
 expect(document.querySelector('[data-chat-session]')).toBe(chat);
});
it("matches the conversation action groups and supports menu keyboard dismissal", async () => {
 await mount();
 const actions=document.querySelector<HTMLButtonElement>('[aria-label="Conversation actions"]')!;
 await flush(()=>actions.click());
 const items=[...document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')];
 expect(items.map(row=>row.textContent)).toEqual(['Rename','Pin','New side chat','Fork','Add scheduled task…','Share','Copy','Open in new window','Open in','Archive']);
 const enabled=items.filter(row=>!row.disabled);
 expect(document.activeElement).toBe(enabled[0]);
 await flush(()=>enabled[0].dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true})));
 expect(document.activeElement).toBe(enabled[1]);
 await flush(()=>enabled[1].dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));
 expect(document.querySelector('[role="menu"]')).toBeNull();
 expect(document.activeElement).toBe(actions);
});

it("collapses each column independently without remounting the chat", async () => {
 localStorage.setItem(DEMO_SESSION_KEY, 'saved');
 const source = new MockSource();
 vi.spyOn(source, 'session').mockResolvedValue({session_id: 'saved'} as never);
 await mount(source);
 const chat = document.querySelector('[data-chat-session]');
 const toggle = document.querySelector<HTMLButtonElement>('[aria-label="Toggle navigation"]')!;
 await flush(() => toggle.click());
 expect(document.querySelector<HTMLElement>('#jaeger-navigation-context')?.hidden).toBe(true);
 expect(toggle.getAttribute('aria-expanded')).toBe('false');
 expect(document.querySelector('[data-chat-session]')).toBe(chat);
 await flush(() => toggle.click());
 expect(document.querySelector<HTMLElement>('#jaeger-navigation-context')?.hidden).toBe(false);
 expect(document.querySelector('[data-chat-session]')).toBe(chat);
 expect(document.querySelector('.jg-stable-demo__profile')?.textContent).toContain('Jaeger');
});

it("collapses sidebar groups independently while keeping the same conversation and right panel", async () => {
 localStorage.setItem(DEMO_SESSION_KEY, 'saved');
 const source = new MockSource();
 vi.spyOn(source, 'session').mockResolvedValue({session_id: 'saved'} as never);
 const create = vi.spyOn(source, 'createSession');
 await mount(source);
 const chat = document.querySelector('[data-chat-session]');
 await flush(() => document.querySelector<HTMLButtonElement>('[aria-label="Toggle tools workspace"]')!.click());
 for (const title of ['Pinned', 'Projects', 'Recents']) {
  const button = [...document.querySelectorAll<HTMLButtonElement>('.jg-sidebar-section__toggle')].find(b => b.textContent === title)!;
  expect(button).toHaveAttribute('aria-expanded', 'true');
  await flush(() => button.click());
  expect(button).toHaveAttribute('aria-expanded', 'false');
  expect(document.getElementById(button.getAttribute('aria-controls')!)?.hidden).toBe(true);
  expect(document.querySelector('[data-chat-session]')).toBe(chat);
  expect(document.querySelector('[aria-label="Tools workspace"]')).not.toBeNull();
 }
 const recents = [...document.querySelectorAll<HTMLButtonElement>('.jg-sidebar-section__toggle')].find(b => b.textContent === 'Recents')!;
 await flush(() => recents.click());
 expect(recents).toHaveAttribute('aria-expanded', 'true');
 expect(document.querySelector('.jg-sidebar-section__toggle')).toHaveAttribute('aria-expanded', 'false');
 expect(create).not.toHaveBeenCalled();
});

it("restores each sidebar group's expansion preference after reopening the app", async () => {
 await mount();
 const pinned = document.querySelector<HTMLButtonElement>('.jg-sidebar-section__toggle')!;
 await flush(() => pinned.click());
 await flush(() => root.unmount());
 await mount();
 const groups = [...document.querySelectorAll<HTMLButtonElement>('.jg-sidebar-section__toggle')];
 expect(groups.find(button => button.textContent === 'Pinned')).toHaveAttribute('aria-expanded', 'false');
 expect(groups.find(button => button.textContent === 'Projects')).toHaveAttribute('aria-expanded', 'true');
 expect(groups.find(button => button.textContent === 'Recents')).toHaveAttribute('aria-expanded', 'true');
});

it("keeps disclosures usable if browser storage refuses writes", async () => {
 const storage = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {throw new Error('Storage unavailable');});
 try {
  await mount();
  const pinned = document.querySelector<HTMLButtonElement>('.jg-sidebar-section__toggle')!;
  await flush(() => pinned.click());
  expect(pinned).toHaveAttribute('aria-expanded', 'false');
  await flush(() => pinned.click());
  expect(pinned).toHaveAttribute('aria-expanded', 'true');
 } finally {storage.mockRestore();}
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

it("accepts slow unread-history responses without overlapping polling forever", async () => {
 const source = new MockSource();
 Object.assign(source, {messageReadState: {load: vi.fn(), save: vi.fn(), clear: vi.fn()}});
 let resolve!: (rows: Awaited<ReturnType<MockSource['sessions']>>) => void;
 const pending = new Promise<Awaited<ReturnType<MockSource['sessions']>>>(done => { resolve = done; });
 const sessions = vi.spyOn(source, 'sessions').mockReturnValue(pending);
 const visibility = Object.getOwnPropertyDescriptor(document, "hidden");
 Object.defineProperty(document, "hidden", {configurable:true,value:false});
 vi.useFakeTimers();
 try {
  const el=document.createElement("div"); document.body.append(el); root=createRoot(el);
  await act(async () => { root.render(<StableDemo source={source}/>); });
  await act(async () => { vi.advanceTimersByTime(15000); });
  expect(sessions).toHaveBeenCalledTimes(2); // initial history + one in-flight refresh
  await act(async () => { resolve([{session_id:'slow',title:'Slow durable conversation',unread:{request_id:'request',role:'assistant'}}] as never); });
  expect(document.body.textContent).toContain('Slow durable conversation');
  expect(document.querySelector('[aria-label="Unread"]')).not.toBeNull();
 } finally { vi.useRealTimers(); if(visibility)Object.defineProperty(document,"hidden",visibility); else delete (document as unknown as {hidden?:boolean}).hidden; }
});

it('forks saved history through the existing Gateway route only on explicit selection', async()=>{
 history.replaceState(null,'','/chat?session=original');
 const source=new MockSource();Object.defineProperty(source,'kind',{value:'live'});
 vi.spyOn(source,'session').mockImplementation(async id=>({session_id:id,title:'Original'}));
 vi.spyOn(source,'sessions').mockResolvedValue([{session_id:'original',title:'Original'}]);
 const fetch=vi.fn().mockResolvedValue({ok:true,text:async()=>JSON.stringify({session_id:'forked',title:'Original (fork)'})});vi.stubGlobal('fetch',fetch);
 try {
  await mount(source);
  await flush(()=>document.querySelector<HTMLButtonElement>('[aria-label="Conversation actions"]')!.click());
  await flush(()=>[...document.querySelectorAll('button')].find(button=>button.textContent==='Fork')!.click());
  expect(fetch).not.toHaveBeenCalled();
  await flush(()=>[...document.querySelectorAll('button')].find(button=>button.textContent==='Fork conversation')!.click());await flush();
  expect(fetch.mock.calls[0][0]).toBe('/v1/sessions/original/branch');
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({title:'Original (fork)'});
  expect(document.querySelector('[data-chat-session]')).toHaveAttribute('data-chat-session','forked');
 } finally {vi.unstubAllGlobals();}
});

it('keeps the same chat mounted and the toolbar available while settings change the center page', async () => {
 await mount();
 const chat = document.querySelector('[data-chat-session]');
 const toolbar = document.querySelector('[aria-label="Conversation toolbar"]');
 await flush(() => document.querySelector<HTMLButtonElement>('[aria-label="Settings"]')!.click());
 expect(location.pathname).toBe('/settings/appearance');
 expect(document.querySelector('[aria-label="Conversation toolbar"]')).toBe(toolbar);
 expect(document.querySelector('[data-chat-session]')).toBe(chat);
 expect(document.querySelector('[data-workspace-embedded]')).toBeTruthy();
 expect(document.querySelector('.jg-stable-demo')).not.toHaveAttribute('hidden');
});
