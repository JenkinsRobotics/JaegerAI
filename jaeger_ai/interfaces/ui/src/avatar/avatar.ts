import type { ChatTurn } from "../chat/host";
export const AVATAR_STATES = ['idle','working','making_something','waiting','connecting','milestone_level_up'] as const;
export type ClipState = typeof AVATAR_STATES[number];
export const STATUS_TEXT: Record<ClipState,string> = {idle:'Ready',working:'Is working',making_something:'Is making something',waiting:'Is waiting on a specialist',connecting:'Is connecting',milestone_level_up:'Finished'};
export interface AvatarBundle { portrait:string; videos:Partial<Record<ClipState,string>> }
const base='/assets/avatar/jaeger/';
export const JAEGER_BUNDLE: AvatarBundle = {portrait:base+'portrait.png',videos:Object.fromEntries(AVATAR_STATES.map(state=>[state,base+(state==='milestone_level_up'?'milestone':state)+'.mp4']))};
const logged=new Set<string>();
export function missingClip(key:string) {if(!logged.has(key)){logged.add(key);console.warn(`[avatar] ${key} unavailable; using portrait`);}}
export function getAvatar(character:string,state:ClipState,bundle:AvatarBundle=JAEGER_BUNDLE) {
 const video=(character==='jaeger'||character==='native:jaeger')?bundle.videos[state]:undefined;
 if(!video)missingClip(`${character}/${state}`);
 return {portrait:bundle.portrait,src:video||bundle.portrait,kind:video?'video' as const:'portrait' as const};
}
/** Only explicit structured tool/handoff states influence the presentation. */
export function activityState(turn:ChatTurn|undefined,running:boolean):ClipState {
 if(!running && turn?.state!=='pending')return 'idle';
 if(turn?.parts.some(p=>p.kind==='handoff' && ['pending','running','queued','accepted'].includes(p.status||'')))return 'waiting';
 if(turn?.parts.some(p=>p.kind==='toolInvocation' && ['executing','streaming'].includes(p.state) && /(^|[._])(write_file|generate_image|image_generate|render|create_artifact|save_file)([._]|$)/.test(p.toolName)))return 'making_something';
 return 'working';
}
