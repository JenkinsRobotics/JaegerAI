import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { DocumentsPage } from './DocumentsPage';
const api = vi.hoisted(() => ({ get: vi.fn(), send: vi.fn(), toast: vi.fn(), models: vi.fn() }));
vi.mock('./webui', () => ({ getJson: api.get, sendJson: api.send }));
vi.mock('./models', () => ({ loadModels: api.models, isCloud: () => false, isEmbedding: () => false }));
vi.mock('../chat/Markdown', () => ({ Markdown: ({ text }: { text: string }) => <div>{text}</div> }));
vi.mock('./ui', () => ({ useToast: () => api.toast, Empty: ({ title }: { title: string }) => <p>{title}</p>, SkeletonRows: () => <p>Loading</p>, Segmented: () => null, PageHead: ({ actions }: { actions: React.ReactNode }) => <div>{actions}</div>, Sheet: ({ children, onClose }: { children: React.ReactNode; onClose: () => void }) => <aside><button onClick={onClose}>Close</button>{children}</aside> }));
const a = { id: 'a', title: 'Alpha', body: 'original', updated_at: 1 }, b = { id: 'b', title: 'Beta', body: 'second', updated_at: 1 };
function deferred<T>() { let resolve!: (v: T) => void; let reject!: (e: Error) => void; const promise = new Promise<T>((yes,no) => { resolve=yes; reject=no; }); return { promise, resolve, reject }; }
async function mount() { const view = render(<DocumentsPage params={new URLSearchParams({ doc: 'a' })} />); await act(async () => {}); return view; }
function body(text: string) { fireEvent.change(screen.getByLabelText('Markdown'), { target: { value: text } }); }
function openBeta() { fireEvent.click(screen.getByText('Beta')); }
beforeEach(() => { sessionStorage.clear(); vi.clearAllMocks(); api.models.mockResolvedValue({models:[{name:"local"}]}); api.get.mockImplementation(async (url: string) => url === '/v1/documents' ? { documents: [a,b] } : url.endsWith('/b') ? b : a); api.send.mockResolvedValue({ ...a, updated_at: 2 }); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
it('preserves draft and original revision on remount with a newer server document', async () => {
 const view = await mount(); body('unsaved'); view.unmount(); api.get.mockImplementation(async (url: string) => url === '/v1/documents' ? { documents: [a,b] } : { ...a, body: 'remote edit', updated_at: 3 });
 await mount(); expect((screen.getByLabelText('Markdown') as HTMLTextAreaElement).value).toBe('unsaved');
 fireEvent.click(screen.getByText('Save ⌘S')); await act(async () => {}); expect(api.send).toHaveBeenCalledWith('PUT','/v1/documents/a',expect.objectContaining({ expected_updated_at: 1 }));
});
it('ignores an older open response', async () => {
 const pending = deferred<typeof a>(); api.get.mockImplementation((url: string) => url === '/v1/documents' ? Promise.resolve({ documents: [a,b] }) : url.endsWith('/a') ? pending.promise : Promise.resolve(b));
 await mount(); openBeta(); await act(async () => {}); await act(async () => pending.resolve(a)); expect((screen.getByLabelText('Title') as HTMLInputElement).value).toBe('Beta');
});
it('serializes saves and retains edits typed during a save', async () => {
 const pending = deferred<typeof a>(); api.send.mockReturnValue(pending.promise); await mount(); body('first'); fireEvent.keyDown(window,{key:'s',ctrlKey:true}); fireEvent.keyDown(window,{key:'s',ctrlKey:true}); body('newer');
 expect(api.send).toHaveBeenCalledTimes(1); await act(async () => pending.resolve({...a, body:'first',updated_at:2})); expect((screen.getByLabelText('Markdown') as HTMLTextAreaElement).value).toBe('newer'); expect(screen.getByText('Save ⌘S')).toBeTruthy();
});
it('does not apply save or delete responses to another document', async () => {
 const pending = deferred<typeof a>(); api.send.mockReturnValue(pending.promise); await mount(); body('edit'); fireEvent.keyDown(window,{key:'s',ctrlKey:true}); openBeta(); await act(async () => {}); await act(async () => pending.resolve({...a,body:'edit',updated_at:2})); expect((screen.getByLabelText('Title') as HTMLInputElement).value).toBe('Beta');
 const deletion = deferred<typeof a>(); api.send.mockReturnValue(deletion.promise); vi.spyOn(window,'confirm').mockReturnValue(true); fireEvent.click(screen.getByText('Delete')); fireEvent.click(screen.getByText('Alpha')); await act(async () => {}); await act(async () => deletion.resolve(b)); expect(screen.getByLabelText('Title')).toBeTruthy();
});
it('keeps failed save dirty without success toast', async () => { await mount(); body('keep'); api.send.mockRejectedValue(new Error('conflict')); fireEvent.click(screen.getByText('Save ⌘S')); await act(async()=>{}); expect(screen.getByText('Save ⌘S')).toBeTruthy(); expect(api.toast).not.toHaveBeenCalledWith('Saved'); });
it('does not reopen dismissed AI or replace changed text', async () => {
 const pending = deferred<{text:string}>(); api.send.mockReturnValue(pending.promise); await mount(); fireEvent.click(screen.getByText('Improve')); fireEvent.click(screen.getByText('Close')); await act(async()=>pending.resolve({text:'replacement'})); expect(screen.queryByText('Discard')).toBeNull();
 const next = deferred<{text:string}>(); api.send.mockReturnValue(next.promise); fireEvent.click(screen.getByText('Improve')); body('new text'); await act(async()=>next.resolve({text:'replacement'})); const replace = screen.queryByText(/Replace document/); if(replace) fireEvent.click(replace); expect((screen.getByLabelText('Markdown') as HTMLTextAreaElement).value).toBe('new text');
});
it('does not show AI output for another document', async () => { const pending=deferred<{text:string}>(); api.send.mockReturnValue(pending.promise); await mount(); fireEvent.click(screen.getByText('Improve')); openBeta(); await act(async()=>{}); await act(async()=>pending.resolve({text:'replacement'})); expect(screen.queryByText('Discard')).toBeNull(); });
it('restores per-document drafts after navigation and explicitly reloads only after confirmation', async () => {
 await mount(); body('keep me'); openBeta(); await act(async()=>{}); fireEvent.click(screen.getByText('Alpha')); await act(async()=>{}); expect((screen.getByLabelText('Markdown') as HTMLTextAreaElement).value).toBe('keep me');
 const confirm = vi.spyOn(window,'confirm').mockReturnValue(false); fireEvent.click(screen.getByText('Discard draft and reload')); expect((screen.getByLabelText('Markdown') as HTMLTextAreaElement).value).toBe('keep me');
 confirm.mockReturnValue(true); fireEvent.click(screen.getByText('Discard draft and reload')); await act(async()=>{}); expect((screen.getByLabelText('Markdown') as HTMLTextAreaElement).value).toBe('original'); expect(sessionStorage.getItem('jaeger.ui.documents.draft.v1.a')).toBeNull();
});
it('retains an in-flight draft after unmount without claiming success', async () => {
 const pending=deferred<typeof a>(); api.send.mockReturnValue(pending.promise); const view=await mount(); body('pending draft'); fireEvent.keyDown(window,{key:'s',ctrlKey:true}); view.unmount(); await act(async()=>pending.resolve({...a,body:'pending draft',updated_at:2})); expect(api.toast).not.toHaveBeenCalledWith('Saved'); await mount(); expect((screen.getByLabelText('Markdown') as HTMLTextAreaElement).value).toBe('pending draft');
});
it('shows storage failures and preserves malformed storage until explicitly discarded', async () => {
 sessionStorage.setItem('jaeger.ui.documents.draft.v1.a','broken'); await mount(); expect(screen.getByRole('status').textContent).toContain('could not be read'); expect(sessionStorage.getItem('jaeger.ui.documents.draft.v1.a')).toBe('broken');
 body('new text'); expect(sessionStorage.getItem('jaeger.ui.documents.draft.v1.a')).toBe('broken'); openBeta(); await act(async()=>{});
 vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('quota');}); body('keep in editor'); expect(screen.getByRole('status').textContent).toContain('Keep this editor open'); expect((screen.getByLabelText('Markdown') as HTMLTextAreaElement).value).toBe('keep in editor');
 openBeta(); await act(async()=>{}); expect((screen.getByLabelText('Markdown') as HTMLTextAreaElement).value).toBe('keep in editor');
 const event = new Event('beforeunload', {cancelable:true}); window.dispatchEvent(event); expect(event.defaultPrevented).toBe(true);
 vi.restoreAllMocks(); vi.spyOn(window,'confirm').mockReturnValue(true); fireEvent.click(screen.getByText('Discard draft and reload')); await act(async()=>{}); fireEvent.click(screen.getByText('Alpha')); await act(async()=>{}); fireEvent.click(screen.getByText('Discard draft and reload')); await act(async()=>{});

});
it('adopts normalized server fields on confirmed save and clears only the saved draft', async () => {
 await mount(); fireEvent.change(screen.getByLabelText('Title'),{target:{value:'  Trimmed  '}}); body('saved body'); api.send.mockResolvedValue({...a,title:'Trimmed',body:'saved body',updated_at:2}); fireEvent.click(screen.getByText('Save ⌘S')); await act(async()=>{}); expect((screen.getByLabelText('Title') as HTMLInputElement).value).toBe('Trimmed'); expect(screen.getByText('Saved')).toBeTruthy(); expect(sessionStorage.getItem('jaeger.ui.documents.draft.v1.a')).toBeNull();
});
it('serializes repeated creates and does not replace newer navigation on response', async () => {
 const pending=deferred<typeof a>(); api.send.mockReturnValue(pending.promise); await mount(); fireEvent.click(screen.getAllByText('New document')[0]); fireEvent.click(screen.getAllByText('New document')[0]); expect(api.send).toHaveBeenCalledTimes(1); openBeta(); await act(async()=>{}); await act(async()=>pending.resolve({...a,id:'new'})); expect((screen.getByLabelText('Title') as HTMLInputElement).value).toBe('Beta');
});
it('disables editor changes during delete and keeps draft on delete rejection', async () => {
 await mount(); body('precious'); vi.spyOn(window,'confirm').mockReturnValue(true); const pending=deferred<never>(); api.send.mockReturnValue(pending.promise); fireEvent.click(screen.getByText('Delete')); expect((screen.getByLabelText('Markdown') as HTMLTextAreaElement).disabled).toBe(true);
 await act(async()=>pending.reject(new Error("delete failed"))); expect((screen.getByLabelText('Markdown') as HTMLTextAreaElement).value).toBe('precious'); expect(sessionStorage.getItem('jaeger.ui.documents.draft.v1.a')).toContain('precious'); expect(api.toast).not.toHaveBeenCalledWith('Deleted');
});
it('keeps independently edited tab drafts when another tab saves', async () => {
 const realStorage = window.sessionStorage;
 const storage = () => { const data = new Map<string,string>(); return { getItem: (key:string)=>data.get(key)??null, setItem:(key:string,value:string)=>{data.set(key,value);}, removeItem:(key:string)=>{data.delete(key);} }; };
 const tabOne=storage(), tabTwo=storage();
 try {
  vi.stubGlobal('sessionStorage',tabOne); const first=await mount(); fireEvent.change(within(first.container).getByLabelText('Markdown'),{target:{value:'one'}});
  vi.stubGlobal('sessionStorage',tabTwo); const second=await mount(); fireEvent.change(within(second.container).getByLabelText('Markdown'),{target:{value:'two'}});
  vi.stubGlobal('sessionStorage',tabOne); api.send.mockResolvedValue({...a,body:'one',updated_at:2}); fireEvent.click(within(first.container).getByText('Save ⌘S')); await act(async()=>{}); first.unmount();
  expect(tabOne.getItem('jaeger.ui.documents.draft.v1.a')).toBeNull(); expect(tabTwo.getItem('jaeger.ui.documents.draft.v1.a')).toContain('two');
  second.unmount(); vi.stubGlobal('sessionStorage',tabTwo); const restored=await mount(); expect((within(restored.container).getByLabelText('Markdown') as HTMLTextAreaElement).value).toBe('two');
 } finally { vi.stubGlobal('sessionStorage',realStorage); }
});
it('recovers drafts when the server is unavailable or the document was remotely deleted', async () => {
 const view=await mount(); body('recover offline'); view.unmount(); api.get.mockImplementation(async(url:string)=>{if(url==='/v1/documents') return {documents:[]}; throw Error('404 no such document');}); await mount(); expect((screen.getByLabelText('Markdown') as HTMLTextAreaElement).value).toBe('recover offline'); expect(screen.getByRole('status').textContent).toContain('Server document is unavailable'); expect(api.send).not.toHaveBeenCalled();
});
it('offers recovery without a route id or server list entry and warns on tab close after unmount', async () => {
 const view=await mount(); body('orphan draft'); view.unmount(); const closing=new Event('beforeunload',{cancelable:true}); window.dispatchEvent(closing); expect(closing.defaultPrevented).toBe(true);
 api.get.mockImplementation(async(url:string)=>{if(url==='/v1/documents') return {documents:[]}; throw Error('offline');}); const recovered=render(<DocumentsPage params={new URLSearchParams()} />); await act(async()=>{}); fireEvent.click(within(recovered.container).getByText('Recover draft: Alpha')); await act(async()=>{}); expect((screen.getByLabelText('Markdown') as HTMLTextAreaElement).value).toBe('orphan draft');
});
it('rejects mismatched save responses without clearing or relabeling the draft', async () => {
 await mount(); body('retain'); api.send.mockResolvedValue({...b,updated_at:2}); fireEvent.click(screen.getByText('Save ⌘S')); await act(async()=>{}); expect((screen.getByLabelText('Title') as HTMLInputElement).value).toBe('Alpha'); expect(screen.getByText('Save ⌘S')).toBeTruthy(); expect(sessionStorage.getItem('jaeger.ui.documents.draft.v1.a')).toContain('retain'); expect(api.toast).not.toHaveBeenCalledWith('Saved');
});
it('rejects malformed open data and provides a working document-list retry', async () => {
 api.get.mockRejectedValue(new Error('offline')); await mount(); expect(screen.getByText('Documents unavailable')).toBeTruthy(); expect(screen.queryByLabelText('Title')).toBeNull(); api.get.mockResolvedValue({documents:[a,b]}); fireEvent.click(screen.getByText('Retry documents')); await act(async()=>{}); expect(screen.getByText('Beta')).toBeTruthy(); api.get.mockResolvedValue({...b,updated_at:Infinity}); openBeta(); await act(async()=>{}); expect(screen.queryByLabelText('Title')).toBeNull();
});

it('shows model-load failure and recovers through explicit retry', async () => {
 api.models.mockRejectedValue(new Error('models offline')); await mount(); expect(screen.getByText('Models could not be loaded: models offline')).toBeTruthy(); api.models.mockResolvedValue({models:[{name:'local'}]}); fireEvent.click(screen.getByText('Retry models')); await act(async()=>{}); expect((screen.getByText('Improve') as HTMLButtonElement).disabled).toBe(false); expect(screen.queryByText('Retry models')).toBeNull();
});

it('retains a return to the old base while a different save completes after navigation', async () => {
 const pending=deferred<typeof a>(); api.send.mockReturnValue(pending.promise); const view=await mount(); body('submitted change'); fireEvent.keyDown(window,{key:'s',ctrlKey:true}); body(a.body);
 expect(sessionStorage.getItem('jaeger.ui.documents.draft.v1.a')).toContain('original'); openBeta(); await act(async()=>{}); view.unmount();
 await act(async()=>pending.resolve({...a,body:'submitted change',updated_at:2})); api.get.mockImplementation(async(url:string)=>url==='/v1/documents'?{documents:[a,b]}:{...a,body:'submitted change',updated_at:2}); await mount();
 expect((screen.getByLabelText('Markdown') as HTMLTextAreaElement).value).toBe(a.body); expect(screen.getByRole('status').textContent).toContain('server document changed'); expect((screen.getByText('Save ⌘S') as HTMLButtonElement).disabled).toBe(false); expect(sessionStorage.getItem('jaeger.ui.documents.draft.v1.a')).toContain('original');
});

it('keeps a reverted draft unreconciled after a committed save loses its response', async () => {
 const pending=deferred<typeof a>(); api.send.mockReturnValue(pending.promise); await mount(); body('committed version'); fireEvent.keyDown(window,{key:'s',ctrlKey:true}); body(a.body); await act(async()=>pending.reject(new Error('network response lost')));
 expect(screen.getByRole('status').textContent).toContain('Save outcome is unconfirmed'); expect((screen.getByText('Save ⌘S') as HTMLButtonElement).disabled).toBe(false); expect(screen.queryByText('Saved')).toBeNull();
 body('temporary edit'); body(a.body); expect(sessionStorage.getItem('jaeger.ui.documents.draft.v1.a')).toContain('original'); expect(JSON.parse(sessionStorage.getItem('jaeger.ui.documents.draft.v1.a')!).unreconciled).toBe(true); openBeta(); await act(async()=>{});
 api.get.mockResolvedValue({...a,body:'committed version',updated_at:2}); fireEvent.click(screen.getByText('Alpha')); await act(async()=>{}); expect((screen.getByLabelText('Markdown') as HTMLTextAreaElement).value).toBe(a.body); expect((screen.getByText('Save ⌘S') as HTMLButtonElement).disabled).toBe(false); expect(api.toast).not.toHaveBeenCalledWith('Saved');
});

it('preserves a clean document recovery copy after deletion loses its response', async () => {
 const pending=deferred<typeof a>(); api.send.mockReturnValue(pending.promise); const view=await mount(); vi.spyOn(window,'confirm').mockReturnValue(true); fireEvent.click(screen.getByText('Delete')); await act(async()=>pending.reject(new Error('delete response lost')));
 expect(screen.getByRole('status').textContent).toContain('Deletion outcome is unconfirmed'); expect(screen.queryByText('Saved')).toBeNull(); expect(JSON.parse(sessionStorage.getItem('jaeger.ui.documents.draft.v1.a')!).draft.body).toBe(a.body); view.unmount();
 api.get.mockImplementation(async(url:string)=>{if(url==='/v1/documents') return {documents:[]}; throw Error('404');}); await mount(); expect((screen.getByLabelText('Markdown') as HTMLTextAreaElement).value).toBe(a.body); expect(screen.queryByText('Saved')).toBeNull(); expect(api.toast).not.toHaveBeenCalledWith('Deleted');
});
it('reports an unknown create outcome and checks the list without replaying create', async () => {
 await mount(); api.send.mockRejectedValue(new Error('creation response lost')); const reads=api.get.mock.calls.length; fireEvent.click(screen.getAllByText('New document')[0]); await act(async()=>{});
 expect(screen.getByRole('status').textContent).toContain('Creation outcome is unconfirmed'); expect(api.get.mock.calls.length).toBeGreaterThan(reads); expect(api.send).toHaveBeenCalledTimes(1);
});
