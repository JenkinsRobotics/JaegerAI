import { act, fireEvent, render, screen, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MinimalChat } from "./MinimalChat";
import type { ChatHost } from "./host";
import { useMessagePress } from "./useMessagePress";
vi.mock("./drafts", () => ({ readDraft: async () => ({ text: "", files: [] }), writeDraft: async () => undefined }));

afterEach(() => { cleanup(); vi.useRealTimers(); localStorage.clear(); });
function pointer(element: Element, type: string, fields: Record<string, unknown> = {}) {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.assign(event, { pointerType: "touch", pointerId: 1, isPrimary: true, button: 0, clientX: 20, clientY: 30, ...fields });
  fireEvent(element, event); return event;
}
function PressFixture({ open }: { open: Parameters<typeof useMessagePress>[0] }) {
  const { cancel, ...handlers } = useMessagePress(open);
  return <div {...handlers} onScroll={cancel}><div className="jg-bubble" tabIndex={0}>Message <a href="#">Link</a></div></div>;
}
describe("message touch and keyboard gestures", () => {
  it("opens on a stationary hold, suppresses release click, and cancels short taps", () => {
    vi.useFakeTimers(); const open = vi.fn(); const view = render(<PressFixture open={open} />); const bubble = view.container.querySelector('.jg-bubble')!;
    pointer(bubble, 'pointerdown'); act(() => vi.advanceTimersByTime(200)); pointer(bubble, 'pointerup'); act(() => vi.advanceTimersByTime(500)); expect(open).not.toHaveBeenCalled();
    pointer(bubble, 'pointerdown'); act(() => vi.advanceTimersByTime(460)); expect(open).toHaveBeenCalledExactlyOnceWith(bubble, {x:20,y:30,touch:true});
    expect(bubble.classList.contains('jg-bubble--holding')).toBe(false);
    expect(pointer(bubble, 'pointerup').defaultPrevented).toBe(true);
    const click = new MouseEvent('click', {bubbles:true,cancelable:true}); fireEvent(bubble,click); expect(click.defaultPrevented).toBe(true);
  });
  it.each(['move','cancel','scroll','multitouch','blur','unmount'])('cancels a pending hold on %s', action => {
    vi.useFakeTimers(); const open = vi.fn(); const view = render(<PressFixture open={open} />); const bubble = view.container.querySelector('.jg-bubble')!;
    pointer(bubble,'pointerdown');
    if(action==='move') pointer(bubble,'pointermove',{clientY:60});
    if(action==='cancel') pointer(bubble,'pointercancel');
    if(action==='scroll') fireEvent.scroll(bubble.parentElement!);
    if(action==='multitouch') pointer(bubble,'pointerdown',{pointerId:2,isPrimary:false});
    if(action==='blur') fireEvent(window,new Event('blur'));
    if(action==='unmount') view.unmount();
    act(()=>vi.advanceTimersByTime(1000)); expect(open).not.toHaveBeenCalled(); expect(bubble.classList.contains('jg-bubble--holding')).toBe(false);
  });
  it("leaves desktop selection and interactive child gestures alone, and supports Shift F10", () => {
    vi.useFakeTimers(); const open = vi.fn(); const view = render(<PressFixture open={open} />); const bubble = view.container.querySelector('.jg-bubble')!;
    expect(pointer(bubble,'pointerdown',{pointerType:'mouse'}).defaultPrevented).toBe(false);
    pointer(bubble.querySelector('a')!,'pointerdown'); act(()=>vi.advanceTimersByTime(1000)); expect(open).not.toHaveBeenCalled();
    fireEvent.keyDown(bubble,{key:'F10',shiftKey:true}); expect(open.mock.calls[0][1].touch).toBe(false);
  });
});
function hostFixture() {
  let state = {unread:null as {request_id:string;role:'user'|'assistant'}|null,event_id:0};
  const host = {
    kind:'native', capabilities:{voice:false}, copy:vi.fn().mockResolvedValue(undefined), openExternal:vi.fn(), startTurn:vi.fn(), respondToConfirmation:vi.fn(),
    sessions:{load:vi.fn(async(id:string)=>({id,title:'test',turns:[{turnId:'t1',requestId:'request-1',message:'Question',parts:[{kind:'markdownContent',text:'First paragraph.\n\nSecond paragraph.'}],state:'complete'}]})),list:vi.fn(),save:vi.fn(),delete:vi.fn()},
    messageReadState:{load:vi.fn(async()=>state),save:vi.fn(async(_id:string,unread:typeof state.unread)=>(state={unread,event_id:state.event_id+1})),clear:vi.fn(async()=>(state={unread:null,event_id:state.event_id+1}))},
  };
  return host;
}
async function mounted() { const host=hostFixture(); const view=render(<MinimalChat host={host as unknown as ChatHost} sessionId="actions-test"/>); await act(async()=>{}); const bubble=view.container.querySelector('.jg-bubble--assistant')!; return {host,bubble,view}; }
function open(bubble:Element) { fireEvent.contextMenu(bubble,{clientX:20,clientY:20}); }
it('Copy uses the host clipboard, preserves paragraphs, and reports failure',async()=>{
  const {host,bubble}=await mounted(); open(bubble); fireEvent.click(screen.getByRole('menuitem',{name:'Copy'}));
  await act(async()=>{}); expect(host.copy).toHaveBeenCalledWith('First paragraph.\nSecond paragraph.');
  host.copy.mockRejectedValueOnce(Error('Clipboard denied')); open(bubble); fireEvent.click(screen.getByRole('menuitem',{name:'Copy Request ID'}));
  await act(async()=>{}); expect(screen.getByText("Couldn't copy: Clipboard denied")).toBeTruthy();
});
it('Select Text supports native subset selection without changing the composer',async()=>{
  const {host,bubble}=await mounted(); open(bubble); fireEvent.click(screen.getByRole('menuitem',{name:'Select Text'}));
  const field=screen.getByRole('textbox',{name:'Message text'}) as HTMLTextAreaElement;
  expect(field.readOnly).toBe(true); expect(field.selectionEnd).toBe(field.value.length);
  field.setSelectionRange(0,5); fireEvent.click(screen.getByRole('button',{name:'Copy selection'})); await act(async()=>{});
  expect(host.copy).toHaveBeenCalledWith('First'); expect((screen.getByRole('textbox',{name:'Message'}) as HTMLTextAreaElement).value).toBe('');
  fireEvent.click(screen.getByRole('button',{name:'Done'})); await act(async()=>{}); expect(screen.queryByRole('dialog')).toBeNull(); expect(document.activeElement).toBe(bubble);
});
it('Mark unread waits for receipt, survives remount, and clears explicitly',async()=>{
  const {host,bubble,view}=await mounted(); open(bubble); fireEvent.click(screen.getByRole('menuitem',{name:'Mark as unread'})); await act(async()=>{});
  expect(host.messageReadState.save).toHaveBeenCalledWith('actions-test',{request_id:'request-1',role:'assistant'});
  expect(screen.getByRole('separator',{name:'Unread from here'})).toBeTruthy();
  view.unmount(); render(<MinimalChat host={host as unknown as ChatHost} sessionId="actions-test"/>); await act(async()=>{});
  expect(screen.getByRole('separator',{name:'Unread from here'})).toBeTruthy(); fireEvent.click(screen.getByRole('button',{name:'Mark read'})); await act(async()=>{});
  expect(host.messageReadState.clear).toHaveBeenCalledWith('actions-test'); expect(screen.queryByRole('separator',{name:'Unread from here'})).toBeNull();
});
it('menu supports keyboard navigation, Escape, and a keyboard-invoking message',async()=>{
  const {bubble}=await mounted(); (bubble as HTMLElement).focus(); fireEvent.keyDown(bubble,{key:'F10',shiftKey:true});
  expect(document.activeElement?.textContent).toContain('Reply'); fireEvent.keyDown(document.activeElement!,{key:'End'}); expect(document.activeElement?.textContent).toContain('Copy Request ID');
  fireEvent.keyDown(document.activeElement!,{key:'Escape'}); await act(async()=>{}); expect(screen.queryByRole('menu')).toBeNull();
});

it('never invents a request identity or enables unread when unsupported',async()=>{
  const host=hostFixture();
  const incomplete={...host,messageReadState:undefined,sessions:{...host.sessions,load:async(id:string)=>({id,title:'legacy',turns:[{turnId:'render-only',message:'Old message',parts:[],state:'complete'}]})}};
  const view=render(<MinimalChat host={incomplete as unknown as ChatHost} sessionId="legacy"/>);await act(async()=>{});
  open(view.container.querySelector('.jg-bubble')!);
  expect((screen.getByRole('menuitem',{name:'Copy Request ID'}) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole('menuitem',{name:'Mark as unread'}) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText('No request ID was recorded for this message.')).toBeTruthy();
});

it('Copy retains table cell boundaries and omits embedded UI controls',async()=>{
  const {host,bubble}=await mounted();
  bubble.innerHTML='<table><thead><tr><th>Name</th><th>Value</th></tr></thead><tbody><tr><td>A</td><td>20</td></tr></tbody></table><button>Copy code</button>';
  open(bubble);fireEvent.click(screen.getByRole('menuitem',{name:'Copy'}));await act(async()=>{});
  expect(host.copy).toHaveBeenCalledWith('Name\tValue\nA\t20');
});
