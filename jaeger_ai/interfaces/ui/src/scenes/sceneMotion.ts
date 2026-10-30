/** Visual actions only. Gateway/task status remains authoritative. */
import type { AgentSummary } from '../api/types';
export type SceneAction = 'rest' | 'read' | 'type' | 'listen' | 'attention' | 'check' | 'celebrate' | 'blocked' | 'offline' | 'speak' | 'stretch' | 'sip' | 'look';
export type SceneLayout = 'portrait' | 'desk' | 'workbench';
export interface SceneMedia { url: string; type: 'image' | 'video' }
export interface ScenePack { version: 1; character_id: string; layout: SceneLayout; portrait?: SceneMedia | null; background?: SceneMedia | null; actions: Partial<Record<SceneAction, SceneMedia>> }

export function summaryActivity(summary?: AgentSummary): string | undefined {
  if (['waiting_approval', 'needs_owner', 'blocked', 'error', 'failed', 'offline', 'stopped'].includes(summary?.status ?? '')) return summary?.status;
  return summary?.task?.state ?? summary?.status;
}

export function activityAction(status?: string, speaking = false): SceneAction {
  // Safety/attention states always interrupt ambient motion and speech.
  if (['needs_owner', 'waiting_approval'].includes(status ?? '')) return 'attention';
  if (['blocked', 'failed', 'error'].includes(status ?? '')) return 'blocked';
  if (!status || ['offline', 'stopped', 'unknown', 'cancelled'].includes(status)) return 'offline';
  if (speaking) return 'speak';
  switch (status) {
    case 'thinking': case 'planning': return 'read';
    case 'working': case 'running': return 'type';
    case 'observing': case 'verifying': return 'check';
    case 'listening': case 'waiting': case 'paused': case 'queued': return 'listen';
    case 'done': case 'completed_verified': return 'celebrate';
    case 'idle': return 'rest';
    default: return 'offline';
  }
}

export const ACTION_LABEL: Record<SceneAction, string> = {
  rest: 'Idle', read: 'Thinking', type: 'Working', listen: 'Waiting', attention: 'Needs your attention',
  check: 'Checking', celebrate: 'Completed', blocked: 'Blocked or failed', offline: 'Activity unavailable or stopped',
  speak: 'Speaking', stretch: 'Idle', sip: 'Idle', look: 'Idle',
};

/** Stagger idle actions per identity; no model calls or shared activity state. */
export function ambientAction(id: string, cycle: number): SceneAction {
  const seed = [...id].reduce((value, char) => ((value * 31 + char.charCodeAt(0)) >>> 0), 0);
  return (['look', 'sip', 'stretch'] as const)[(seed + cycle) % 3];
}
