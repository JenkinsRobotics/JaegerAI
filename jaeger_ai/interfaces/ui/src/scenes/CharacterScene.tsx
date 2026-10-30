import { useEffect, useRef, useState } from 'react';
import { AgentAvatar } from '../agents/AgentAvatar';
import { GatewayClient } from '../api/gateway';
import type { AgentSummary } from '../api/types';
import { onNativeEvent } from '../platform/native';
import { ACTION_LABEL, activityAction, ambientAction, summaryActivity, type SceneAction, type SceneLayout, type SceneMedia, type ScenePack } from './sceneMotion';
import './scenes.css';

export interface CharacterSceneProps {
  id: string; name: string; src?: string; preset?: string | null; characterId?: string;
  status?: string;
  /** Only set from observed audio playback, never from text streaming. */
  speaking?: boolean;
}
const gateway = new GatewayClient();

function useSceneVisibility(ref: React.RefObject<HTMLElement | null>) {
  const [visible, setVisible] = useState(typeof document === 'undefined' || !document.hidden);
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    let nativeVisible = true, intersecting = true;
    const update = () => setVisible(!document.hidden && nativeVisible && intersecting);
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const motion = () => setReduced(media.matches);
    motion(); media.addEventListener('change', motion);
    document.addEventListener('visibilitychange', update);
    const off = onNativeEvent(event => {
      const detail = event as typeof event & { visible?: boolean };
      if (event.type === 'window.visibility' && typeof detail.visible === 'boolean') {
        nativeVisible = detail.visible; update();
      }
    });
    const observer = typeof IntersectionObserver === 'function' ? new IntersectionObserver(entries => {
      intersecting = entries.some(entry => entry.isIntersecting); update();
    }) : undefined;
    if (ref.current) observer?.observe(ref.current);
    return () => { off(); observer?.disconnect(); document.removeEventListener('visibilitychange', update); media.removeEventListener('change', motion); };
  }, [ref]);
  return { visible, reduced };
}

function Media({ media, playing, className, fallback }: { media: SceneMedia; playing: boolean; className: string; fallback: () => void }) {
  const video = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const el = video.current;
    if (!el) return;
    if (playing) void el.play().catch(() => { /* Autoplay denial leaves a still frame; no retry loop. */ });
    else el.pause();
    return () => el.pause();
  }, [playing, media.url]);
  return media.type === 'video'
    ? <video ref={video} className={className} src={media.url} muted loop playsInline preload="metadata" onError={fallback} aria-hidden="true" />
    : <img className={className} src={media.url} alt="" onError={fallback} />;
}

/** Data-only layered scene. The pack supplies art; this component owns playback only. */
export function CharacterScene({ id, name, src, preset, characterId, status, speaking = false }: CharacterSceneProps) {
  const ref = useRef<HTMLElement>(null);
  const { visible, reduced } = useSceneVisibility(ref);
  const [paused, setPaused] = useState(false);
  const [pack, setPack] = useState<ScenePack>();
  const [layoutOverride, setLayout] = useState<SceneLayout>();
  const [ambient, setAmbient] = useState<SceneAction>();
  const [badMedia, setBadMedia] = useState<string[]>([]);
  const [portraitFailed, setPortraitFailed] = useState(false);
  const baseAction = activityAction(status, speaking);
  const playing = visible && !reduced && !paused && baseAction !== 'offline';
  useEffect(() => {
    setPack(undefined); setBadMedia([]); setPortraitFailed(false); setLayout(undefined);
    if (!characterId) return;
    const controller = new AbortController();
    void gateway.json<ScenePack>(`/v1/characters/${encodeURIComponent(characterId)}/scene`, undefined, undefined, undefined, controller.signal)
      .then(value => { if (!controller.signal.aborted && value.version === 1 && value.character_id === characterId) setPack(value); })
      .catch(() => { /* Older Gateway or unavailable pack: keep the agent's own art. */ });
    return () => controller.abort();
  }, [characterId, id]);
  useEffect(() => { setPortraitFailed(false); }, [src]);
  useEffect(() => {
    setAmbient(undefined);
    if (!playing || baseAction !== 'rest') return;
    let cycle = 0;
    let timer: ReturnType<typeof setTimeout>;
    const schedule = () => { timer = setTimeout(() => {
      setAmbient(ambientAction(id, cycle++));
      timer = setTimeout(() => { setAmbient(undefined); schedule(); }, 3800);
    }, 10000 + (id.length % 7) * 900); };
    schedule();
    return () => clearTimeout(timer);
  }, [id, baseAction, playing]);
  // Never let the previous frame's ambient action obscure a new activity.
  const action = baseAction === 'rest' && playing ? ambient ?? baseAction : baseAction;
  const layout = layoutOverride ?? pack?.layout ?? 'desk';
  const usable = (media?: SceneMedia | null) => media && !badMedia.includes(media.url) ? media : undefined;
  const clip = usable(pack?.actions?.[action]);
  const background = usable(pack?.background);
  const portrait = usable(pack?.portrait);
  const artwork = !portraitFailed && !preset ? (portrait?.type === 'image' ? portrait.url : undefined) ?? src : undefined;
  const failed = (url: string) => setBadMedia(previous => [...previous, url]);
  return <section ref={ref} className="jg-scene" aria-label={`${name} living scene`} data-agent-id={id} data-action={action} data-layout={layout} data-playing={playing}>
    <div className="jg-scene__stage" aria-hidden="true">
      {background && <Media media={background} playing={playing} className="jg-scene__background" fallback={() => failed(background.url)} />}
      <div className="jg-scene__window"><i /><i /></div>
      <div className="jg-scene__shelf"><i /><i /><i /><span /></div>
      {clip ? <Media key={clip.url} media={clip} playing={playing} className="jg-scene__clip" fallback={() => failed(clip.url)} /> : <>
        <div className="jg-scene__chair" />
        <div className="jg-scene__actor">
          <div className="jg-scene__torso" />
          <div className="jg-scene__head">
            {artwork ? <img src={artwork} alt="" onError={() => setPortraitFailed(true)} /> : <AgentAvatar id={id} name={name} preset={preset} size={82} />}
          </div>
          <div className="jg-scene__arm jg-scene__arm--left" /><div className="jg-scene__arm jg-scene__arm--right" />
        </div>
        <div className="jg-scene__desk"><div className="jg-scene__monitor"><i /><i /><i /></div><div className="jg-scene__book" /><div className="jg-scene__cup" /><div className="jg-scene__plant"><i /><i /><i /></div></div>
      </>}
      {baseAction === 'attention' && <span className="jg-scene__attention">!</span>}
    </div>
    <div className="jg-scene__caption"><strong>{name}</strong><span>{ACTION_LABEL[action]}</span></div>
    <div className="jg-scene__controls">
      <label>Scene <select aria-label={`Scene for ${name}`} value={layout} onChange={event => setLayout(event.target.value as SceneLayout)}><option value="portrait">Portrait</option><option value="desk">Study</option><option value="workbench">Workshop</option></select></label>
      <button type="button" onClick={() => setPaused(value => !value)} aria-pressed={paused}>{paused ? 'Resume animation' : 'Pause animation'}</button>
    </div>
  </section>;
}

/** Apple UI does not share the classic store. Read the existing scoped summary,
 * never the global newest presence event or that screen's descriptive status. */
export function LiveCharacterScene(props: Omit<CharacterSceneProps, 'status'>) {
  const [activity, setActivity] = useState<{ id: string; status?: string }>();
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const read = async () => {
      try {
        const data = await gateway.json<{ agents?: AgentSummary[] }>('/v1/agents/summary', undefined, undefined, undefined, controller.signal);
        const summary = data.agents?.find(row => row.id === props.id);
        if (!controller.signal.aborted) setActivity({ id: props.id, status: summaryActivity(summary) });
      } catch { if (!controller.signal.aborted) setActivity({ id: props.id }); }
      if (!controller.signal.aborted) timer = setTimeout(read, 3000);
    };
    void read();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [props.id]);
  return <CharacterScene key={props.id} {...props} status={activity?.id === props.id ? activity.status : undefined} />;
}

export function CharacterSceneWindow({ onClose, children, name }: { onClose: () => void; children: React.ReactNode; name: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { const el = dialog.current; el?.showModal(); return () => el?.close(); }, []);
  return <dialog ref={dialog} className="jg-scene-dialog" aria-label={`${name} character window`} onCancel={onClose}>
    <button type="button" className="jg-scene-dialog__close" onClick={onClose} autoFocus>Close character window</button>{children}
  </dialog>;
}
