/** Agent avatars (AVATAR-SPEC.md, 2026-10-31): presence → avatar state, panel modes, API client. Pure + tiny. */
import { getJson, sendJson } from "../unified/webui";

export type AvatarState = "idle" | "listening" | "thinking" | "speaking" | "blocked" | "offline";
export type PanelMode = "expanded" | "rail" | "mini" | "hidden";
export const EMOTIONS = ["neutral", "happy", "warm", "focused", "curious", "concerned", "surprised", "sad"] as const;
export type Emotion = (typeof EMOTIONS)[number];
export const PREVIEW_STATES: AvatarState[] = ["idle", "listening", "thinking", "speaking"];

const MAP: Record<string, AvatarState> = {
  idle: "idle", done: "idle", waiting: "idle",
  listening: "listening",
  thinking: "thinking", planning: "thinking", working: "thinking", observing: "thinking", verifying: "thinking",
  blocked: "blocked", failed: "blocked", needs_owner: "blocked", waiting_approval: "blocked", error: "blocked",
  offline: "offline", stopped: "offline",
};

/** Presence is the only input (§2); speaking (TTS playing) overrides everything; mic open → listening. */
export function avatarStateFor(presence: string | undefined, opts: { speaking?: boolean; listening?: boolean } = {}): AvatarState {
  if (opts.speaking) return "speaking";
  if (opts.listening) return "listening";
  return MAP[(presence ?? "idle").toLowerCase()] ?? "idle";
}

export const STATE_TEXT: Record<AvatarState, string> = { idle: "Idle", listening: "Listening", thinking: "Thinking", speaking: "Speaking", blocked: "Needs you", offline: "Offline" };

export function ariaLabel(name: string, state: AvatarState, emotion: string) {
  return `${name} avatar, ${STATE_TEXT[state].toLowerCase()}, ${emotion}`;
}

const MODE_KEY = "jaeger.avatar.panel";
/** RESPONSIVE-SYSTEM §3 avatar collapse: docked (expanded/wide) → 64px rail (regular) → floating mini (medium, compact) → hidden (short). */
export function defaultMode(cls: string, short = false): PanelMode {
  if (short) return "hidden";
  return cls === "expanded" || cls === "wide" ? "expanded" : cls === "regular" ? "rail" : "mini";
}
/** Remembered per agent AND per size class (a choice on Mac doesn't follow you to the phone). */
export function loadMode(agentId: string, cls = "expanded", short = false, store: Pick<Storage, "getItem"> = localStorage): PanelMode {
  const def = defaultMode(cls, short);
  if (short) return def;
  try { const v = (JSON.parse(store.getItem(MODE_KEY) ?? "{}") as Record<string, PanelMode>)[`${agentId}@${cls}`]; return v && ["expanded", "rail", "mini", "hidden"].includes(v) ? v : def; } catch { return def; }
}
export function saveMode(agentId: string, mode: PanelMode, cls = "expanded", store: Pick<Storage, "getItem" | "setItem"> = localStorage) {
  let all: Record<string, PanelMode> = {};
  try { all = JSON.parse(store.getItem(MODE_KEY) ?? "{}"); } catch { /* reset */ }
  all[`${agentId}@${cls}`] = mode;
  store.setItem(MODE_KEY, JSON.stringify(all));
}
/** ⌥⌘A cycles expanded → rail → hidden → expanded (mini is entered explicitly). */
export const nextMode = (m: PanelMode): PanelMode => (m === "expanded" ? "rail" : m === "rail" ? "hidden" : "expanded");

export function clampOrbit(yaw: number, pitch: number) { return { yaw: Math.max(-60, Math.min(60, yaw)), pitch: Math.max(-10, Math.min(25, pitch)) }; }
export const clampZoom = (z: number) => Math.max(0.6, Math.min(2.5, z));

// ── API (WebUI avatar_api.py) ─────────────────────────────────────────
export interface AssetRecord { id: string; sha256: string; uri: string; name: string; bytes: number; mime: string; format: "vrm" | "glb" | "rive" | "image"; format_version?: string | null;
  width?: number; height?: number; triangles?: number; materials?: number; textures?: number; morphs?: string[]; animations?: string[]; expressions?: string[];
  meta?: Record<string, unknown> | null; note?: string; budget?: { devices: Record<string, { ok: boolean; over: string[] }>; warnings: string[] } }
export interface AvatarExt { schema: string; format: AssetRecord["format"]; format_version?: string | null; version: string; asset?: { uri: string; sha256?: string; bytes?: number; mime?: string };
  fallback: { uri?: string; ref?: string; sha256?: string }; states: Record<string, { animation?: string | null; expression?: string }>; emotions: Record<string, Record<string, number>>;
  visemes?: { profile: string; map: Record<string, string | null> }; customization?: { primary?: string; accent?: string; accessories?: string[] };
  license: { spdx?: string; url?: string | null; author?: string; source?: string; commercial?: boolean; redistribution?: boolean }; history?: { version: string; sha256: string; at: string }[]; [k: string]: unknown }
export interface Live { emotion: Emotion; intensity: number; updated_at: number | null; source: string }
export interface AvatarRecord { agent_id: string; avatar: AvatarExt | null; asset: AssetRecord | null; fallback_asset: AssetRecord | null; live: Live; report?: { warnings: string[] } }
export interface Versions { current: { version: string; sha256: string; format: string } | null; history: { version: string; sha256: string; at: string; restorable: boolean }[] }

const enc = encodeURIComponent;
export const avatarApi = {
  get: (id: string) => getJson<AvatarRecord>(`/v1/agents/${enc(id)}/avatar`),
  save: (id: string, avatar: AvatarExt) => sendJson<AvatarRecord>("PUT", `/v1/agents/${enc(id)}/avatar`, { avatar }),
  versions: (id: string) => getJson<Versions>(`/v1/agents/${enc(id)}/avatar/versions`),
  restore: (id: string, version: string) => sendJson<AvatarRecord>("POST", `/v1/agents/${enc(id)}/avatar/restore`, { version }),
  emotion: (id: string, emotion: Emotion, intensity: number) => sendJson<Live>("PUT", `/v1/agents/${enc(id)}/avatar/emotion`, { emotion, intensity }),
  upload: async (name: string, blob: Blob): Promise<AssetRecord> => {
    const buf = new Uint8Array(await blob.arrayBuffer());
    let bin = ""; for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
    return sendJson<AssetRecord>("POST", "/v1/assets", { name, data_base64: btoa(bin) });
  },
};
export const assetUrl = (uri?: string) => { const m = /^jaeger-asset:\/\/([a-f0-9]{64})$/.exec(uri ?? ""); return m ? `/v1/assets/${m[1]}/file` : undefined; };

/** Designer placeholders bundled with the UI (GenerateImage originals, AVATAR-SPEC "Art"). */
export const LIBRARY = [
  { name: "Nova", file: "char-nova.jpg", kind: "character" },
  { name: "Atlas", file: "bot-atlas.jpg", kind: "bot" },
  { name: "Relay", file: "bot-relay.jpg", kind: "bot" },
] as const;

/** A minimal valid extension for a portrait (image) or an uploaded model + portrait fallback. */
export function buildExtension(model: AssetRecord, fallback: AssetRecord, prev?: AvatarExt | null, author = "Matthew Jenkins"): AvatarExt {
  const has = (n: string) => (model.expressions ?? []).includes(n);
  const ex = (n: string) => (model.format === "vrm" && has(n) ? n : "neutral");
  return {
    ...(prev ?? {}),
    schema: "jaeger.avatar/1", format: model.format, format_version: model.format === "vrm" ? "1.0" : model.format === "glb" ? "2.0" : null,
    version: prev?.version ?? "1.0.0",
    asset: { uri: model.uri, sha256: model.sha256 }, fallback: { uri: fallback.uri, sha256: fallback.sha256 },
    states: { idle: { animation: null, expression: "neutral" }, listening: { animation: null, expression: ex("relaxed") }, thinking: { animation: null, expression: "neutral" },
      speaking: { animation: null, expression: "neutral" }, blocked: { animation: null, expression: ex("surprised") }, offline: { animation: null, expression: "neutral" } },
    emotions: model.format === "vrm"
      ? Object.fromEntries([["neutral", { neutral: 1 }], ...(["happy", "sad", "surprised", "relaxed"].filter(has).map((e) => [e, { [e]: 1 }]))])
      : { neutral: { neutral: 1 } },
    visemes: model.format === "vrm" && has("aa") ? { profile: "vrm5", map: { A: "aa", I: "ih", U: "ou", E: "ee", O: "oh", sil: null } } : undefined,
    license: prev?.license ?? { spdx: "LicenseRef-Jaeger-Placeholder", author, source: model.name, commercial: true, redistribution: true },
    history: prev?.history,
  };
}
