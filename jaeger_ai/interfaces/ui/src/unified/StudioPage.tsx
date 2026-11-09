/**
 * Creative Studio (unified UI): generate images with a real provider, keep them in an asset
 * library (~/.jaeger/studio), and arrange assets and notes on a board. Providers come from
 * GET /v1/studio/providers; an unavailable one is shown disabled with its setup note and is
 * never simulated. Send to chat uploads the image into the chosen agent's conversation.
 */
import { useRoute } from "../shell/router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { JaegerSource } from "../api/source";
import type { Agent } from "../api/types";
import { label, visible } from "../agents/agentsLogic";
import { Badge, Empty, Segmented, Sheet, SkeletonRows, useToast, PageHead } from "./ui";
import "./companion.css";
import { getJson, sendJson } from "./webui";

export interface Provider { id: string; name: string; kind: string; available: boolean; cost: string; note: string | null }
export interface Asset { id: string; name: string; mime: string; size: number; created_at: number; source: string; tags: string[]; prompt?: string | null; provider?: string | null }
export interface BoardItem { id: string; kind: "asset" | "note"; asset_id?: string; text?: string; color?: string; x: number; y: number; w: number; h: number }
const fileUrl = (a: Pick<Asset, "id">) => `/v1/studio/assets/${a.id}/file`;
const kb = (n: number) => (n > 1 << 20 ? `${(n / (1 << 20)).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

function readAsBase64(file: File): Promise<string> {
  return new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(",")[1] ?? ""); r.onerror = () => rej(r.error); r.readAsDataURL(file); });
}

export function StudioPage({ source, agents, onNavigate, initialSection = "create" }: { initialSection?: "create" | "library" | "board"; source: JaegerSource; agents: Agent[]; onNavigate: (to: string) => void }) {
  const toast = useToast();
  const route = useRoute();
  const section = route.page === "studio" ? route.params.get("section") : null;
  const [tab, setTab] = useState<"create" | "library" | "board">(initialSection);
  useEffect(() => { setTab(section === "library" || section === "board" ? section : initialSection); }, [section, initialSection]);
  const [assets, setAssets] = useState<Asset[] | null>(null);
  const [err, setErr] = useState<string>();
  const load = useCallback(() => getJson<{ assets: Asset[] }>("/v1/studio/assets").then((r) => { setAssets(r.assets); setErr(undefined); }, (e: Error) => setErr(e.message)), []);
  useEffect(() => { void load(); }, [load]);
  const fileInput = useRef<HTMLInputElement>(null);
  const importFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    let n = 0;
    for (const f of Array.from(files)) {
      try { await sendJson("POST", "/v1/studio/assets", { name: f.name, mime: f.type, data_base64: await readAsBase64(f), tags: ["imported"] }); n++; }
      catch (e) { toast(`${f.name}: ${(e as Error).message}`, "error"); }
    }
    if (n) { toast(`Imported ${n} image${n > 1 ? "s" : ""}`); await load(); setTab("library"); }
  };
  return (
    <div className="jg-u-page jg-studio">
      <PageHead title={initialSection === "library" ? "Media" : "Imagine"} subtitle="Generate images, keep an asset library and lay ideas out on a board." actions={<>
          <Segmented label="Studio section" value={tab} onChange={setTab} options={[{ value: "create", label: "Generate" }, { value: "library", label: `Library${assets ? ` (${assets.length})` : ""}` }, { value: "board", label: "Board" }]} />
          <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple hidden onChange={(e) => { void importFiles(e.target.files); e.target.value = ""; }} />
          <button type="button" className="jg-u-btn" onClick={() => fileInput.current?.click()}>Import images</button>
        </>} />
      {err && <p className="jg-u-error" role="alert">Studio storage unavailable: {err}</p>}
      {tab === "create" && <Generate onMade={async () => { await load(); }} assets={assets} />}
      {tab === "library" && <Library assets={assets} reload={load} source={source} agents={agents} onNavigate={onNavigate} />}
      {tab === "board" && <Board assets={assets ?? []} source={source} />}
    </div>
  );
}

function Generate({ onMade, assets }: { onMade: () => Promise<void>; assets: Asset[] | null }) {
  const toast = useToast();
  const [providers, setProviders] = useState<Provider[] | null>(null);
  const [pid, setPid] = useState("");
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>();
  useEffect(() => {
    getJson<{ providers: Provider[] }>("/v1/studio/providers").then((r) => { setProviders(r.providers); setPid(r.providers.find((p) => p.available)?.id ?? ""); }, (e: Error) => setErr(e.message));
  }, []);
  const ready = providers?.some((p) => p.available);
  const recent = (assets ?? []).filter((a) => a.source === "generated").slice(0, 8);
  const run = async () => {
    setBusy(true); setErr(undefined);
    try { const a = await sendJson<Asset & { elapsed_s: number }>("POST", "/v1/studio/generate", { provider: pid, prompt }); toast(`Generated in ${a.elapsed_s}s`); await onMade(); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="jg-ui-split">
      <section className="jg-u-card" aria-label="Generate">
        <h2>What should we imagine?</h2>
        {!providers && !err && <SkeletonRows />}
        {providers && (
          <form className="jg-studio__form" onSubmit={(e) => { e.preventDefault(); void run(); }}>
            <fieldset className="jg-studio__providers" aria-label="Provider">
              {providers.map((p) => (
                <label key={p.id} className="jg-studio__provider" data-off={!p.available || undefined}>
                  <input type="radio" name="provider" value={p.id} checked={pid === p.id} disabled={!p.available} onChange={() => setPid(p.id)} />
                  <span><strong>{p.name}</strong> <Badge tone={p.available ? "ok" : undefined}>{p.available ? "Ready" : "Not set up"}</Badge><br /><small>{p.cost}{p.note ? ` · ${p.note}` : ""}</small></span>
                </label>))}
            </fieldset>
            <label className="jg-ui-field">Prompt<textarea rows={4} maxLength={2000} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="A brushed-steel robot reading in a sunlit library, isometric" disabled={!ready} /></label>
            {err && <p className="jg-u-error" role="alert">{err}</p>}
            <div className="jg-ui-actions">
              {!ready && <span className="jg-u-note">No image provider is set up on this Mac yet — see the notes above. You can still import images.</span>}
              <button className="jg-u-btn jg-u-btn--primary" disabled={!ready || !pid || !prompt.trim() || busy}>{busy ? "Generating…" : "Generate"}</button>
            </div>
          </form>)}
      </section>
      <aside className="jg-ui-inspector" aria-label="Recent generations">
        <h3>Recent generations</h3>
        {!assets ? <SkeletonRows /> : recent.length ? <div className="jg-studio__thumbs">{recent.map((a) => <img key={a.id} src={fileUrl(a)} alt={a.prompt ?? a.name} loading="lazy" />)}</div>
          : <Empty title="Nothing generated yet">Generated images land in the Library.</Empty>}
      </aside>
    </div>
  );
}

function Library({ assets, reload, source, agents, onNavigate }: { assets: Asset[] | null; reload: () => Promise<void>; source: JaegerSource; agents: Agent[]; onNavigate: (to: string) => void }) {
  const [q, setQ] = useState("");
  const [tag, setTag] = useState("");
  const [open, setOpen] = useState<Asset>();
  const tags = useMemo(() => [...new Set((assets ?? []).flatMap((a) => a.tags))].sort(), [assets]);
  const shown = (assets ?? []).filter((a) => (!tag || a.tags.includes(tag)) && (!q || `${a.name} ${a.prompt ?? ""} ${a.tags.join(" ")}`.toLowerCase().includes(q.toLowerCase())));
  return (
    <>
      <div className="jg-ui-toolbar jg-mb-4">
        <input className="jg-u-search" type="search" placeholder="Search assets" aria-label="Search assets" value={q} onChange={(e) => setQ(e.target.value)} />
        {tags.length > 0 && <Segmented label="Tag" value={tag} onChange={setTag} options={[{ value: "", label: "All" }, ...tags.slice(0, 8).map((t) => ({ value: t, label: t }))]} />}
      </div>
      {!assets ? <SkeletonRows n={4} /> : !shown.length ? <Empty title={assets.length ? "No assets match" : "Your library is empty"}>{assets.length ? "Try another search or tag." : "Generate or import images to start."}</Empty> : (
        <ul className="jg-studio__grid" aria-label="Assets">
          {shown.map((a) => (
            <li key={a.id}><button type="button" className="jg-studio__tile" onClick={() => setOpen(a)}>
              <img src={fileUrl(a)} alt={a.prompt ?? a.name} loading="lazy" />
              <span><strong>{a.name}</strong><small>{a.tags.join(" · ") || kb(a.size)}</small></span>
            </button></li>))}
        </ul>)}
      {open && <AssetSheet asset={open} onClose={() => setOpen(undefined)} reload={reload} source={source} agents={agents} onNavigate={onNavigate} />}
    </>
  );
}

function AssetSheet({ asset, onClose, reload, source, agents, onNavigate }: { asset: Asset; onClose: () => void; reload: () => Promise<void>; source: JaegerSource; agents: Agent[]; onNavigate: (to: string) => void }) {
  const toast = useToast();
  const [tags, setTags] = useState(asset.tags.join(", "));
  const [agentId, setAgentId] = useState(agents.find((a) => a.primary)?.id ?? agents[0]?.id ?? "");
  const [note, setNote] = useState(`Here's an image from my Studio: ${asset.name}`);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const saveTags = async () => {
    try { await sendJson("PUT", `/v1/studio/assets/${asset.id}`, { tags: tags.split(",").map((t) => t.trim()).filter(Boolean) }); toast("Tags saved"); await reload(); }
    catch (e) { toast((e as Error).message, "error"); }
  };
  const remove = async () => {
    try { await sendJson("DELETE", `/v1/studio/assets/${asset.id}`); toast("Deleted"); await reload(); onClose(); } catch (e) { toast((e as Error).message, "error"); }
  };
  const canSend = Boolean(source.uploadAttachment && source.agentHome);
  const sendToChat = async () => {
    if (!source.uploadAttachment || !source.agentHome) return;
    setBusy(true);
    try {
      const blob = await (await fetch(fileUrl(asset), { credentials: "include" })).blob();
      const b64 = await readAsBase64(new File([blob], asset.name, { type: asset.mime }));
      const home = await source.agentHome(agentId);
      const att = await source.uploadAttachment(home.session_id, { name: `${asset.name.replace(/[^\w .-]/g, "_").slice(0, 60)}${asset.mime === "image/png" ? ".png" : ""}`, mime: asset.mime, data_base64: b64 });
      await source.send(home.session_id, note, crypto.randomUUID(), [att.attachment_id]);
      toast("Sent to chat");
      onNavigate(`/chat?agent=${encodeURIComponent(agentId)}`);
    } catch (e) { toast(`Couldn't send: ${(e as Error).message}`, "error"); } finally { setBusy(false); }
  };
  return (
    <Sheet title={asset.name} onClose={onClose}>
      <img className="jg-studio__preview" src={fileUrl(asset)} alt={asset.prompt ?? asset.name} />
      <dl className="jg-ui-kv">
        <dt>Source</dt><dd>{asset.source}{asset.provider ? ` · ${asset.provider}` : ""}</dd>
        {asset.prompt && <><dt>Prompt</dt><dd>{asset.prompt}</dd></>}
        <dt>Size</dt><dd>{kb(asset.size)} · {asset.mime}</dd>
        <dt>Added</dt><dd>{new Date(asset.created_at * 1000).toLocaleString()}</dd>
      </dl>
      <form onSubmit={(e) => { e.preventDefault(); void saveTags(); }} className="jg-ui-toolbar">
        <label className="jg-ui-field jg-grow">Tags (comma separated)<input value={tags} onChange={(e) => setTags(e.target.value)} /></label>
        <button className="jg-u-btn jg-self-end">Save tags</button>
      </form>
      {canSend && (
        <form className="jg-stack jg-stack--tight" onSubmit={(e) => { e.preventDefault(); void sendToChat(); }}>
          <label className="jg-ui-field">Send to<select value={agentId} onChange={(e) => setAgentId(e.target.value)}>{agents.filter(visible).map((a) => <option key={a.id} value={a.id}>{label(a)}</option>)}</select></label>
          <label className="jg-ui-field">Message<input value={note} onChange={(e) => setNote(e.target.value)} /></label>
          <div className="jg-ui-actions"><button className="jg-u-btn jg-u-btn--primary" disabled={busy || !agentId || !note.trim()}>{busy ? "Sending…" : "Send to chat"}</button></div>
        </form>)}
      <div className="jg-ui-actions">
        <a className="jg-u-btn" href={fileUrl(asset)} download={asset.name}>Download</a>
        {confirmDelete ? <><span className="jg-u-note">Delete permanently?</span><button type="button" className="jg-u-btn" onClick={() => setConfirmDelete(false)}>Keep</button><button type="button" className="jg-u-btn jg-u-btn--danger" onClick={() => void remove()}>Delete</button></>
          : <button type="button" className="jg-u-btn jg-u-btn--danger" onClick={() => setConfirmDelete(true)}>Delete…</button>}
      </div>
    </Sheet>
  );
}

// A successful HTTP response is not enough to authorize whole-board replacement.
function boardItems(value: unknown): BoardItem[] {
  const items = value && typeof value === "object" && "items" in value ? value.items : undefined;
  if (!Array.isArray(items) || items.length > 300) throw new Error("Invalid board data; editing is disabled.");
  const ids = new Set<string>();
  for (const item of items) {
    if (!item || typeof item !== "object" || typeof item.id !== "string" || ids.has(item.id)
      || (item.kind !== "note" && item.kind !== "asset")
      || ![item.x, item.y, item.w, item.h].every((n) => typeof n === "number" && Number.isFinite(n) && n >= -5000 && n <= 20000)
      || (item.text !== undefined && typeof item.text !== "string")
      || (item.color !== undefined && typeof item.color !== "string")
      || (item.asset_id !== undefined && typeof item.asset_id !== "string")) {
      throw new Error("Invalid board data; editing is disabled.");
    }
    ids.add(item.id);
  }
  return items;
}

export function Board({ assets, source }: { assets: Asset[]; source?: JaegerSource }) {
  const toast = useToast();
  const [loaded, setLoaded] = useState<{ source: JaegerSource | undefined; items: BoardItem[] }>();
  const items = loaded?.source === source ? loaded?.items ?? null : null;
  const [picking, setPicking] = useState(false);
  const [err, setErr] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  const dirty = useRef(false);
  const revision = useRef(0);
  const lifetime = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    setLoaded(undefined); setErr(undefined); setPicking(false); dirty.current = false;
    getJson<unknown>("/v1/studio/board", controller.signal).then((value) => {
      if (!controller.signal.aborted) setLoaded({ source, items: boardItems(value) });
    }).catch((e: Error) => { if (!controller.signal.aborted) setErr(e.message); });
    return () => controller.abort();
  }, [source, attempt]);
  useEffect(() => {
    if (!items || !dirty.current) return;
    const controller = lifetime.current;
    const version = revision.current;
    const t = setTimeout(() => { sendJson("PUT", "/v1/studio/board", { items }).then(() => {
      if (!controller?.signal.aborted && version === revision.current) dirty.current = false;
    }, (e: Error) => { if (!controller?.signal.aborted) toast(`Board not saved: ${e.message}`, "error"); }); }, 600);
    return () => clearTimeout(t);
  }, [items, toast]);
  const change = (fn: (xs: BoardItem[]) => BoardItem[]) => {
    if (!items) return;
    dirty.current = true; revision.current++;
    setLoaded((current) => current && current.source === source ? { source, items: fn(current.items) } : current);
  };
  const add = (it: Omit<BoardItem, "id" | "x" | "y">) => change((xs) => [...xs, { ...it, id: crypto.randomUUID().slice(0, 12), x: 24 + (xs.length % 6) * 28, y: 24 + (xs.length % 6) * 28 }]);
  const drag = (id: string, mode: "move" | "size") => (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest("textarea,button")) return;
    e.preventDefault();
    const start = { x: e.clientX, y: e.clientY }, it = items!.find((i) => i.id === id)!;
    const move = (ev: PointerEvent) => {
      const dx = ev.clientX - start.x, dy = ev.clientY - start.y;
      change((xs) => xs.map((i) => i.id !== id ? i : mode === "move" ? { ...i, x: Math.max(0, it.x + dx), y: Math.max(0, it.y + dy) } : { ...i, w: Math.max(80, it.w + dx), h: Math.max(60, it.h + dy) }));
    };
    const up = () => { removeEventListener("pointermove", move); removeEventListener("pointerup", up); };
    addEventListener("pointermove", move); addEventListener("pointerup", up);
  };
  const nudge = (id: string) => (e: React.KeyboardEvent) => {
    const d = e.shiftKey ? 40 : 8, k = e.key;
    const dx = k === "ArrowRight" ? d : k === "ArrowLeft" ? -d : 0, dy = k === "ArrowDown" ? d : k === "ArrowUp" ? -d : 0;
    if (!dx && !dy) return;
    e.preventDefault();
    change((xs) => xs.map((i) => (i.id === id ? { ...i, x: Math.max(0, i.x + dx), y: Math.max(0, i.y + dy) } : i)));
  };
  const byId = new Map(assets.map((a) => [a.id, a]));
  return (
    <>
      <div className="jg-ui-toolbar jg-mb-4">
        <button type="button" className="jg-u-btn" disabled={!items} onClick={() => add({ kind: "note", text: "", color: "yellow", w: 200, h: 140 })}>Add note</button>
        <button type="button" className="jg-u-btn" disabled={!items || !assets.length} onClick={() => setPicking(true)}>Add asset</button>
        <span className="jg-u-note">{items ? "Drag to move, drag the corner to resize, arrow keys nudge. Changes save automatically." : "Editing is disabled until the board loads."}</span>
      </div>
      {err && <div role="alert"><p className="jg-u-error">Board unavailable: {err}</p><button type="button" className="jg-u-btn" onClick={() => setAttempt((n) => n + 1)}>Retry loading board</button></div>}
      {!items ? !err && <><p role="status">Loading board…</p><SkeletonRows /></> : (
        <div className="jg-board-canvas" aria-label="Board">
          {!items.length && <Empty title="Empty board">Add notes and assets to arrange ideas.</Empty>}
          {items.map((i) => {
            const a = i.asset_id ? byId.get(i.asset_id) : undefined;
            return (
              <div key={i.id} className="jg-board-item" data-kind={i.kind} data-color={i.color} tabIndex={0} aria-label={i.kind === "note" ? "Note" : a?.name ?? "Asset"}
                style={{ left: i.x, top: i.y, width: i.w, height: i.h }} onPointerDown={drag(i.id, "move")} onKeyDown={nudge(i.id)}>
                {i.kind === "note"
                  ? <textarea aria-label="Note text" value={i.text} placeholder="Note…" maxLength={4000} onChange={(e) => change((xs) => xs.map((x) => (x.id === i.id ? { ...x, text: e.target.value } : x)))} />
                  : a ? <img src={fileUrl(a)} alt={a.name} draggable={false} /> : <span className="jg-u-note">Asset deleted</span>}
                <button type="button" className="jg-board-item__x" aria-label="Remove from board" onClick={() => change((xs) => xs.filter((x) => x.id !== i.id))}>×</button>
                <span className="jg-board-item__size" aria-hidden="true" onPointerDown={(e) => { e.stopPropagation(); drag(i.id, "size")(e); }} />
              </div>);
          })}
        </div>)}
      {picking && (
        <Sheet title="Add an asset to the board" onClose={() => setPicking(false)}>
          <ul className="jg-studio__grid">{assets.map((a) => (
            <li key={a.id}><button type="button" className="jg-studio__tile" onClick={() => { add({ kind: "asset", asset_id: a.id, w: 240, h: 180 }); setPicking(false); }}>
              <img src={fileUrl(a)} alt={a.name} loading="lazy" /><span><strong>{a.name}</strong></span></button></li>))}
          </ul>
        </Sheet>)}
    </>
  );
}
