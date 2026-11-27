// The app's server (jaeger_ai/interfaces/nexus/serve.py): the Gateway as the agent, and the Mac shell's actions.
import type { AgentEvent } from './chat.ts';

export type Config = { name: string; title: string; suggestions: string[]; gateway: string; webui: string; company?: string;
  face: { name: string; style?: Record<string, unknown>; card?: string } };   // Jaeger's frozen look (look.json)
export type Health = { ready?: boolean; brain?: string; voice?: string | null; hearing?: string; why?: string; session?: string };
export type Task = { request_id: string; title?: string; step?: string; status?: string; elapsed_s?: number };
export type ShellStatus = {
  gateway: string; gateway_up: boolean; webui: string; shell: string; paused: boolean; hotkey: string;
  history_app_names: boolean; login: boolean; droid: string[]; droid_raw: Record<string, unknown>;
  tasks: { state: 'ok' | 'unsupported' | 'unknown'; running: Task[]; recent: Task[] };
  permissions: Record<string, string>;
};
export type Clip = { state: string; text?: string; max_bytes: number };

// Every POST carries X-Jaeger: the server refuses one without it, so no other web page can drive the agent or the Mac.
const post = (url: string, body: object) => fetch(url, { method: 'POST', headers: { 'X-Jaeger': '1' }, body: JSON.stringify(body) });

export const loadConfig = (): Promise<Config> => fetch('ui/config').then(r => r.json());
export const health = (): Promise<Health | null> => fetch('health').then(r => (r.ok ? r.json() : null), () => null);
export const shellStatus = (): Promise<ShellStatus | null> => fetch('shell/status').then(r => (r.ok ? r.json() : null), () => null);
export const pending = (): Promise<{ destination: { target: string; session_id?: string } | null }> => fetch('shell/pending').then(r => r.json());

/** Every event the agent sends from now on; returns a function that stops listening. */
export function listen(on: (e: AgentEvent) => void): () => void {
  const es = new EventSource('agent/events');
  es.onmessage = m => { try { on(JSON.parse(m.data)); } catch { /* a keep-alive or a line that is not JSON */ } };
  return () => es.close();
}

async function ok(r: Response) {
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}

export const say = (text: string) => post('agent/text', { text }).then(ok);
export const interrupt = () => post('agent/interrupt', {}).catch(() => undefined);
export const newChat = () => post('agent/new', {}).then(ok);
/** A recorded clip (16 kHz 16-bit mono, base64) for the Gateway's hearing; resolves to what it heard. */
export const hear = (pcm: string): Promise<string> => post('agent/audio', { pcm }).then(ok).then(j => j.heard ?? '');
/** One of the Mac shell's actions (the same names the menu-bar item uses). */
export const act = (name: string, arg?: unknown) => post('shell/action', { name, arg }).then(ok).then(j => j.result);
export const openLink = (link: string) => post('shell/open', { link }).then(ok);
