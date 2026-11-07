import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { MockSource } from "../api/mock";
import { StableDemo, DEMO_SESSION_KEY } from "./StableDemo";
vi.mock("../chat/ChatPane", () => ({ ChatPane: ({sessionId}: {sessionId: string}) => <div data-chat-session={sessionId}>Real host mount point</div> }));
vi.mock("../unified/TasksWorkspace", () => ({ TasksWorkspace: () => <div>Task mount point</div> }));
(globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
afterEach(async () => { await act(async () => root?.unmount()); localStorage.clear(); document.body.innerHTML = ""; });
const flush = async (f: () => void = () => {}) => act(async () => {f();await new Promise(r=>setTimeout(r,0));});
async function mount(source = new MockSource()) {const el=document.createElement("div");document.body.append(el);root=createRoot(el);await flush(()=>root.render(<StableDemo source={source}/>));return source;}
it("offers only Chat and Tasks while preserving the full workspace link", async () => {
 await mount();expect([...document.querySelectorAll('nav button')].map(e=>e.textContent)).toEqual(["Chat","Tasks"]);
 expect(document.querySelector('a')?.getAttribute('href')).toBe('/?full=1');
});
it("creates an isolated Jaeger session only after the user starts, then keeps chat mounted across task navigation", async () => {
 const source=new MockSource();const create=vi.spyOn(source,'createSession').mockResolvedValue({session_id:'demo-safe',agent_id:'native:jaeger'} as never);
 await mount(source);expect(create).not.toHaveBeenCalled();
 const start=[...document.querySelectorAll('button')].find(e=>e.textContent==='Start conversation')!;await flush(()=>start.click());
 expect(create).toHaveBeenCalledWith({agent_id:'native:jaeger',title:'Jaeger stable chat'});expect(localStorage.getItem(DEMO_SESSION_KEY)).toBe('demo-safe');
 const chat=document.querySelector('[data-chat-session]');await flush(()=>[...document.querySelectorAll('nav button')].find(e=>e.textContent==='Tasks')!.dispatchEvent(new MouseEvent('click',{bubbles:true})));
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
 const toggle = [...document.querySelectorAll('button')].find(b => b.textContent === 'Work panel')!;
 if (!document.querySelector('#jaeger-work-panel')) await flush(() => toggle.click());
 await flush(() => [...document.querySelectorAll('button')].find(b => b.textContent === 'Files & changes')!.click());
 expect(document.querySelector('#jaeger-work-panel')?.textContent).toContain('Start a conversation');
 await flush(() => document.querySelector<HTMLButtonElement>('[aria-label="Close work panel"]')!.click());
 expect(document.querySelector('#jaeger-work-panel')).toBeNull();
 expect(toggle.getAttribute('aria-expanded')).toBe('false');
});
