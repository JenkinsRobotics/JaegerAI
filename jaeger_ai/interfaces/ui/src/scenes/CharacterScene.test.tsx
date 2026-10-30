import { act, useState } from 'react';
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AgentDetails } from '../agents/AgentDetails';
import { GatewayClient } from '../api/gateway';
import { CharacterScene, CharacterSceneWindow, LiveCharacterScene } from './CharacterScene';
import { activityAction, summaryActivity } from './sceneMotion';

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

it('does not infer completion from idle, or speaking from text streaming', () => {
  expect(activityAction('idle')).toBe('rest');
  expect(activityAction('streaming')).toBe('offline');
  expect(activityAction('working')).toBe('type');
  expect(activityAction('completed_verified')).toBe('celebrate');
  expect(activityAction('waiting_approval', true)).toBe('attention');
  expect(activityAction('blocked', true)).toBe('blocked');
  expect(activityAction('stopped', true)).toBe('offline');
  expect(activityAction('working', true)).toBe('speak');
  expect(summaryActivity({id:'a',status:'waiting_approval',task:{task_id:'t',state:'running'}})).toBe('waiting_approval');
});

it('idle activities are interrupted immediately by approval and never run while paused', () => {
  vi.useFakeTimers();
  const { container, rerender } = render(<CharacterScene id="a" name="A" src="/a.png" status="idle" />);
  const scene = () => container.querySelector('.jg-scene')!;
  act(() => { vi.advanceTimersByTime(12000); });
  expect(['look', 'sip', 'stretch']).toContain(scene().getAttribute('data-action'));
  rerender(<CharacterScene id="a" name="A" src="/a.png" status="waiting_approval" />);
  expect(scene()).toHaveAttribute('data-action', 'attention');
  fireEvent.click(screen.getByText('Pause animation'));
  expect(scene()).toHaveAttribute('data-playing', 'false');
  rerender(<CharacterScene id="a" name="A" src="/a.png" status="idle" />);
  act(() => { vi.advanceTimersByTime(60000); });
  expect(scene()).toHaveAttribute('data-action', 'rest');
});

it('pauses for the real native visibility envelope and resumes when shown', () => {
  const { container } = render(<CharacterScene id="robot" name="Robot" preset="robot-shield" status="working" />);
  expect(container.querySelector('.jg-avatar__robot')).toBeTruthy();
  act(() => window.dispatchEvent(new CustomEvent('jaeger:native', { detail: { type: 'window.visibility', visible: false } })));
  expect(container.querySelector('.jg-scene')).toHaveAttribute('data-playing', 'false');
  act(() => window.dispatchEvent(new CustomEvent('jaeger:native', { detail: { type: 'window.visibility', visible: true } })));
  expect(container.querySelector('.jg-scene')).toHaveAttribute('data-playing', 'true');
});

it('honors reduced motion and falls back from broken artwork without replacing identity', () => {
  vi.spyOn(window, 'matchMedia').mockReturnValue({matches:true, addEventListener:vi.fn(), removeEventListener:vi.fn()} as unknown as MediaQueryList);
  const { container } = render(<CharacterScene id="owned" name="Owned" src="/broken.png" status="working" />);
  expect(container.querySelector('.jg-scene')).toHaveAttribute('data-playing', 'false');
  fireEvent.error(container.querySelector('.jg-scene__head img')!);
  expect(container.querySelector('.jg-avatar')).toHaveAttribute('title','Owned');
  expect(container.querySelector('.jg-scene')).toHaveAttribute('data-agent-id','owned');
});

it('loads pack-specific layout/media, then falls back when that clip fails', async () => {
  vi.spyOn(GatewayClient.prototype, 'json').mockResolvedValue({version:1,character_id:'mochi',layout:'workbench',actions:{type:{url:'/v1/characters/mochi/scene/assets/type',type:'image'}}});
  const { container } = render(<CharacterScene id="owned" name="Mochi" characterId="mochi" status="working" />);
  await waitFor(() => expect(container.querySelector('.jg-scene__clip')).toBeTruthy());
  expect(container.querySelector('.jg-scene')).toHaveAttribute('data-layout','workbench');
  fireEvent.error(container.querySelector('.jg-scene__clip')!);
  expect(container.querySelector('.jg-scene__actor')).toBeTruthy();
});

it('scopes live summaries to the requested agent and clears unavailable activity', async () => {
  const read = vi.spyOn(GatewayClient.prototype, 'json').mockResolvedValue({agents:[{id:'other',status:'working'},{id:'owned',status:'blocked'}]});
  const { container, rerender } = render(<LiveCharacterScene id="owned" name="Owned" />);
  await waitFor(() => expect(container.querySelector('.jg-scene')).toHaveAttribute('data-action','blocked'));
  read.mockRejectedValue(new Error('disconnected'));
  rerender(<LiveCharacterScene id="other" name="Other" />);
  await waitFor(() => expect(container.querySelector('.jg-scene')).toHaveAttribute('data-action','offline'));
  expect(read.mock.calls.every(call => call[0] === '/v1/agents/summary')).toBe(true);
});

it('details expose the real character scene and preserve the chosen robot preset', () => {
  const {container, rerender} = render(<AgentDetails agent={{id:'owned',name:'Owned',icon_preset:'robot-shield'}} summary={{id:'owned',status:'working'}} onClose={() => {}} />);
  expect(container.querySelector('.jg-scene')).toHaveAttribute('data-action','type');
  expect(container.querySelector('.jg-scene__head .jg-avatar__robot')).toBeTruthy();
  expect(screen.getByText('Open character window')).toBeTruthy();
  rerender(<AgentDetails agent={{id:'owned',name:'Owned',icon_preset:'robot-shield'}} summary={{id:'owned',status:'working'}} activityAvailable={false} onClose={() => {}} />);
  expect(container.querySelector('.jg-scene')).toHaveAttribute('data-action', 'offline');
  expect(container.querySelector('.jg-scene')).toHaveAttribute('data-playing', 'false');
});

it('character window opens as a modal and Escape closes it', async () => {
  const show = vi.fn(function (this: HTMLDialogElement) { this.open = true; });
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {configurable:true, value:show});
  Object.defineProperty(HTMLDialogElement.prototype, 'close', {configurable:true, value:function (this: HTMLDialogElement) { this.open = false; }});
  function Example() { const [open, setOpen] = useState(true); return open && <CharacterSceneWindow name="Owned" onClose={() => setOpen(false)}><p>Scene</p></CharacterSceneWindow>; }
  render(<Example />);
  expect(show).toHaveBeenCalledTimes(1);
  fireEvent(screen.getByRole('dialog'), new Event('cancel', {bubbles:true}));
  expect(screen.queryByRole('dialog')).toBeNull();
});
