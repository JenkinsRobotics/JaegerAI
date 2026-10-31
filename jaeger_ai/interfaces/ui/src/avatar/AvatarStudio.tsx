/** Agents › agent › Avatar (§1–3): viewer (orbit/zoom/reset/fullscreen, preview bar) + inspector (Customize | File & versions) + Swap. */
import "./avatar.css";
import { useEffect, useRef, useState } from "react";
import type { Agent } from "../api/types";
import { AgentFace } from "../unified/AgentFace";
import { label } from "../agents/agentsLogic";
import { Badge, Segmented, useToast } from "../unified/ui";
import { AvatarStage } from "./AvatarStage";
import { avatarApi, avatarStateFor, buildExtension, clampOrbit, clampZoom, EMOTIONS, LIBRARY, PREVIEW_STATES, STATE_TEXT, type AssetRecord, type AvatarState, type Emotion, type Versions } from "./avatarModel";
import { useAvatar } from "./useAvatar";

const fmtBytes = (n?: number) => (n == null ? "—" : n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.round(n / 1024)} KB`);

export function AvatarStudio({ agent, presence, onBack }: { agent: Agent; presence?: string; onBack: () => void }) {
  const toast = useToast();
  const { record, setRecord, error, reload } = useAvatar(agent.id);
  const [tab, setTab] = useState<"customize" | "file">("customize");
  const [orbit, setOrbit] = useState({ yaw: 0, pitch: 0, zoom: 1 });
  const [preview, setPreview] = useState<AvatarState | null>(null);
  const [previewEmotion, setPreviewEmotion] = useState<Emotion | null>(null);
  const [swap, setSwap] = useState(false);
  const [busy, setBusy] = useState(false);
  const [versions, setVersions] = useState<Versions | null>(null);
  const [stats, setStats] = useState<{ triangles: number; drawCalls: number }>();
  const [intensity, setIntensity] = useState(1);
  const [colors, setColors] = useState<{ primary?: string; accent?: string }>({});
  const view = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number } | null>(null);
  const name = label(agent);
  const ext = record?.avatar ?? null;
  const is3d = ext?.format === "vrm" || ext?.format === "glb";
  useEffect(() => { avatarApi.versions(agent.id).then(setVersions, () => setVersions(null)); }, [agent.id, record?.avatar?.version]);
  useEffect(() => { setColors({ primary: ext?.customization?.primary, accent: ext?.customization?.accent }); }, [ext?.version, ext?.customization?.primary, ext?.customization?.accent]);
  useEffect(() => { if (!preview && !previewEmotion) return; const t = window.setTimeout(() => { setPreview(null); setPreviewEmotion(null); }, 3000); return () => window.clearTimeout(t); }, [preview, previewEmotion]);
  const nudge = (dy: number, dp: number, dz = 0) => setOrbit((o) => ({ ...clampOrbit(o.yaw + dy, o.pitch + dp), zoom: clampZoom(o.zoom + dz) }));
  const reset = () => setOrbit({ yaw: 0, pitch: 0, zoom: 1 });
  const onKey = (e: React.KeyboardEvent) => {
    const k = e.key;
    if (k === "ArrowLeft" && is3d) nudge(-5, 0); else if (k === "ArrowRight" && is3d) nudge(5, 0);
    else if (k === "ArrowUp" && is3d) nudge(0, 5); else if (k === "ArrowDown" && is3d) nudge(0, -5);
    else if (k === "+" || k === "=") nudge(0, 0, 0.1); else if (k === "-") nudge(0, 0, -0.1);
    else if (k === "0") reset(); else if (k.toLowerCase() === "f") void view.current?.requestFullscreen?.(); else return;
    e.preventDefault();
  };
  const save = async (next: NonNullable<typeof ext>, done: string) => {
    setBusy(true);
    try { const r = await avatarApi.save(agent.id, next); setRecord(r); toast(r.report?.warnings?.length ? `${done} · ${r.report.warnings[0]}` : done); }
    catch (e) { toast((e as Error).message, "error"); }
    finally { setBusy(false); }
  };
  const fallbackOf = async (model: AssetRecord): Promise<AssetRecord> => {
    if (model.format === "image") return model;
    if (record?.fallback_asset) return record.fallback_asset;
    throw new Error("Upload a square portrait (≥512 px, ≤400 KB) first; every avatar needs a fallback");
  };
  const useAsset = async (a: AssetRecord) => {
    try {
      const fb = await fallbackOf(a);
      await save(buildExtension(a, fb, ext && ext.format === a.format ? ext : ext ? { ...ext, history: ext.history } : null), `${name}'s avatar saved`);
      setSwap(false);
    } catch (e) { toast((e as Error).message, "error"); }
  };
  const upload = async (f: File) => {
    setBusy(true);
    try { const a = await avatarApi.upload(f.name, f); setBusy(false); if (a.budget?.warnings.length) toast(a.budget.warnings[0]); await useAsset(a); }
    catch (e) { setBusy(false); toast((e as Error).message, "error"); }
  };
  const fromLibrary = async (file: string, nm: string) => {
    setBusy(true);
    try { const blob = await (await fetch(`/${file}`)).blob(); const a = await avatarApi.upload(`${nm}.jpg`, blob); setBusy(false); await useAsset(a); }
    catch (e) { setBusy(false); toast((e as Error).message, "error"); }
  };
  const state = preview ?? avatarStateFor(presence);
  const emotion = previewEmotion ?? record?.live.emotion ?? "neutral";
  const asset = record?.asset ?? null;
  const dirty = ext && (colors.primary !== ext.customization?.primary || colors.accent !== ext.customization?.accent);
  return (
    <section className="jg-av-studio" aria-label={`${name} avatar`}>
      <header className="jg-av-studio__head">
        <button type="button" className="jg-u-btn" onClick={onBack}>‹ Agents</button>
        <AgentFace agent={agent} size={28} /><strong>{name}</strong>
        <span className="jg-av-chip">{(ext?.format ?? "portrait").toUpperCase()}</span>
        {ext && <span className="jg-av-chip">v{ext.version}</span>}
        <span className="jg-av-studio__spacer" />
        <button type="button" className="jg-u-btn jg-u-btn--primary" onClick={() => setSwap(true)}>Swap avatar</button>
      </header>
      {error && <p className="jg-av-hint" role="alert">Couldn't load the avatar: {error}</p>}
      <div className="jg-av-studio__body">
        <div className="jg-av-viewer" ref={view} role="application" tabIndex={0} onKeyDown={onKey}
          aria-label={`${name} avatar viewer. ${is3d ? "Arrow keys orbit, " : ""}plus and minus zoom, 0 resets, F for fullscreen.`}
          onPointerDown={(e) => { if (!is3d || (e.target as HTMLElement).closest("button")) return; drag.current = { x: e.clientX, y: e.clientY }; (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); }}
          onPointerMove={(e) => { if (!drag.current) return; nudge((e.clientX - drag.current.x) * 0.4, (e.clientY - drag.current.y) * 0.2); drag.current = { x: e.clientX, y: e.clientY }; }}
          onPointerUp={() => { drag.current = null; }}
          onWheel={(e) => nudge(0, 0, e.deltaY < 0 ? 0.08 : -0.08)} onDoubleClick={reset}>
          <AvatarStage name={name} record={record} state={state} emotion={emotion} intensity={intensity} orbit={orbit} onStats={setStats}
            portrait={<AgentFace agent={agent} size={240} />} />
          <div className="jg-av-viewer__tools" role="toolbar" aria-label="Viewer tools">
            {is3d && <><button type="button" className="jg-u-btn" aria-label="Rotate left" onClick={() => nudge(-15, 0)}>⟲</button><button type="button" className="jg-u-btn" aria-label="Rotate right" onClick={() => nudge(15, 0)}>⟳</button></>}
            <button type="button" className="jg-u-btn" aria-label="Zoom in" onClick={() => nudge(0, 0, 0.1)}>+</button>
            <button type="button" className="jg-u-btn" aria-label="Zoom out" onClick={() => nudge(0, 0, -0.1)}>−</button>
            <button type="button" className="jg-u-btn" aria-label="Reset view" onClick={reset}>Reset</button>
            <button type="button" className="jg-u-btn" aria-label="Fullscreen" onClick={() => void view.current?.requestFullscreen?.()}>Fullscreen</button>
            {is3d && <span className="jg-av-gizmo" aria-live="off">az {Math.round(orbit.yaw)}° · el {Math.round(orbit.pitch)}° · {orbit.zoom.toFixed(1)}×</span>}
          </div>
          <div className="jg-av-strip" role="group" aria-label="Preview for 3 seconds">
            {PREVIEW_STATES.map((s) => <button key={s} type="button" className="jg-av-strip__item" data-state={s} aria-pressed={state === s} onClick={() => setPreview(s)}><i aria-hidden="true" className="jg-av-pill__dot" />{STATE_TEXT[s]}</button>)}
          </div>
        </div>
        <aside className="jg-av-inspector">
          <Segmented label="Avatar inspector" value={tab} onChange={setTab} options={[{ value: "customize", label: "Customize" }, { value: "file", label: "File & versions" }]} />
          {tab === "customize" ? (
            <div className="jg-av-form">
              <label className="jg-av-field">Primary<input type="color" value={colors.primary ?? "#8d7337"} onChange={(e) => setColors((c) => ({ ...c, primary: e.target.value }))} /></label>
              <label className="jg-av-field">Accent<input type="color" value={colors.accent ?? "#1f6fe5"} onChange={(e) => setColors((c) => ({ ...c, accent: e.target.value }))} /></label>
              {!is3d && <p className="jg-av-hint">Colours are stored on the card; they tint a 3D model's material slots once one is set.</p>}
              <fieldset className="jg-av-emotions"><legend>Expression preview</legend>
                {EMOTIONS.map((e) => <button key={e} type="button" className="jg-u-btn" aria-pressed={emotion === e} onClick={() => setPreviewEmotion(e)}>{e}</button>)}
              </fieldset>
              <label className="jg-av-field">Intensity <input type="range" min={0} max={1} step={0.05} value={intensity} onChange={(e) => setIntensity(Number(e.target.value))} /></label>
              <button type="button" className="jg-u-btn" disabled={busy} onClick={() => void avatarApi.emotion(agent.id, emotion as Emotion, intensity).then(() => reload(), (e: Error) => toast(e.message, "error"))}>Set live emotion</button>
              <button type="button" className="jg-u-btn jg-u-btn--primary" disabled={!ext || !dirty || busy}
                onClick={() => ext && void save({ ...ext, customization: { ...(ext.customization ?? {}), ...colors } }, "Saved new version")}>
                {ext ? `Save as v${bump(ext.version)}` : "Save"}
              </button>
            </div>
          ) : (
            <div className="jg-av-file">
              {!ext ? <p className="jg-av-hint">No avatar saved. Use Swap avatar to pick a placeholder or upload a .vrm, .glb, .riv, .png or .webp.</p> : (
                <dl className="jg-ui-kv">
                  <dt>Format</dt><dd>{ext.format}{ext.format_version ? ` ${ext.format_version}` : ""}</dd>
                  <dt>Size</dt><dd>{fmtBytes(asset?.bytes)}</dd>
                  {asset?.width != null && <><dt>Pixels</dt><dd>{asset.width}×{asset.height}</dd></>}
                  {asset?.triangles != null && <><dt>Triangles</dt><dd>{asset.triangles.toLocaleString()}{stats ? ` (rendered ${stats.triangles.toLocaleString()}, ${stats.drawCalls} draw calls)` : ""}</dd></>}
                  {asset?.materials != null && <><dt>Materials / textures</dt><dd>{asset.materials} / {asset.textures}</dd></>}
                  {asset?.expressions && <><dt>Expressions / visemes</dt><dd>{asset.expressions.join(", ") || "none"}</dd></>}
                  {asset?.morphs && <><dt>Morphs</dt><dd>{asset.morphs.length}</dd></>}
                  {asset?.animations && <><dt>Animations</dt><dd>{asset.animations.join(", ") || "none"}</dd></>}
                  <dt>Licence</dt><dd>{ext.license?.spdx ?? ext.license?.url ?? "—"} · {ext.license?.author ?? "—"}</dd>
                  <dt>Source</dt><dd>{ext.license?.source ?? asset?.name ?? "—"}</dd>
                  <dt>SHA-256</dt><dd className="jg-av-mono">{asset?.sha256 ? `${asset.sha256.slice(0, 12)}…${asset.sha256.slice(-6)}` : "—"}</dd>
                  <dt>Budget</dt><dd className="jg-row">{asset?.budget ? Object.entries(asset.budget.devices).map(([d, v]) => <Badge key={d} tone={v.ok ? "ok" : "warn"}>{d} {v.ok ? "ok" : "over"}</Badge>) : <Badge>n/a</Badge>}</dd>
                </dl>
              )}
              {asset?.note && <p className="jg-av-hint">{asset.note}</p>}
              <h4>Versions</h4>
              {versions?.current ? (
                <ol className="jg-av-versions">
                  <li><strong>v{versions.current.version}</strong> <span>current</span></li>
                  {versions.history.map((h) => (
                    <li key={h.version + h.at}><span>v{h.version}</span> <span className="jg-av-mono">{h.sha256.slice(0, 8)}</span> <span>{new Date(h.at).toLocaleString()}</span>
                      <button type="button" className="jg-u-btn" disabled={!h.restorable || busy} onClick={() => void avatarApi.restore(agent.id, h.version).then((r) => { setRecord(r); toast(`Restored v${h.version} as v${r.avatar?.version}`); }, (e: Error) => toast(e.message, "error"))}>Restore</button></li>
                  ))}
                </ol>
              ) : <p className="jg-av-hint">No versions yet.</p>}
              {ext && <a className="jg-u-btn" href={`/v1/agents/${encodeURIComponent(agent.id)}/avatar/card`} download={`${agent.id}.card.json`} aria-disabled={ext.license?.redistribution === false || undefined}>Export card</a>}
            </div>
          )}
        </aside>
      </div>
      {swap && (
        <div className="jg-av-swap" role="dialog" aria-label="Swap avatar">
          <div className="jg-av-swap__card">
            <header><strong>Swap avatar</strong><button type="button" className="jg-u-btn" onClick={() => setSwap(false)}>Close</button></header>
            <p className="jg-av-hint">Placeholders (portraits). 3D/2D models: upload .vrm (1.0), .glb or .riv. Live2D is pending licence review.</p>
            <ul className="jg-av-library">
              {LIBRARY.map((l) => <li key={l.file}><button type="button" disabled={busy} onClick={() => void fromLibrary(l.file, l.name)}><img src={`/${l.file}`} alt="" /><span>{l.name}</span><small>{l.kind}</small></button></li>)}
            </ul>
            <label className="jg-u-btn jg-u-btn--primary">Upload file…<input type="file" hidden accept=".vrm,.glb,.riv,.png,.webp,.jpg,.jpeg" onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = ""; }} /></label>
          </div>
        </div>
      )}
    </section>
  );
}

function bump(v: string) { const m = /^(\d+)\.(\d+)\.\d+$/.exec(v); return m ? `${m[1]}.${Number(m[2]) + 1}.0` : "1.0.0"; }
