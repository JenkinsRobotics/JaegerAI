import {act,fireEvent,render,renderHook,screen,waitFor} from '@testing-library/react';
import {afterEach,describe,expect,it,vi} from 'vitest';
import {ClipAvatar} from './ClipAvatar';
import {activityState,getAvatar,JAEGER_BUNDLE} from './avatar';
import {useChatAvatar} from './useChatAvatar';
import type {ChatSession,ChatTurn} from '../chat/host';

afterEach(()=>{vi.useRealTimers();vi.restoreAllMocks();});
const session=(state:ChatTurn['state']):ChatSession=>({id:'s',title:'Chat',turns:[{turnId:'t',message:'hello',state,parts:[]}]});
describe('prerendered avatar',()=>{
 it('maps six clips and falls back for missing media',()=>{
  expect(Object.keys(JAEGER_BUNDLE.videos)).toHaveLength(6);
  expect(getAvatar('jaeger','milestone_level_up').src).toContain('milestone.mp4');
  vi.spyOn(console,'warn').mockImplementation(()=>{});
  expect(getAvatar('jaeger','working',{portrait:'/p.png',videos:{}}).kind).toBe('portrait');
 });
 it('plays muted inline loops with visible status; errors leave a portrait',()=>{
  vi.spyOn(console,'warn').mockImplementation(()=>{});
  const {container}=render(<ClipAvatar state="working" showStatus/>);
  const video=container.querySelector('video')!;
  expect(video.muted).toBe(true);
  expect(video.loop).toBe(true);
  expect(video.hasAttribute('playsinline')).toBe(true);
  expect(screen.getByRole('status').textContent).toBe('Is working');
  fireEvent.error(video);
  expect(container.querySelector('video')).toBeNull();
  expect(screen.getByRole('img').getAttribute('src')).toBe(JAEGER_BUNDLE.portrait);
 });
 it('keeps list portraits and custom identities static',()=>{
  const {container,rerender}=render(<ClipAvatar still/>);
  expect(container.querySelector('video')).toBeNull();
  rerender(<ClipAvatar portraitOverride="/custom.png"/>);
  expect(container.querySelector('video')).toBeNull();
  expect(screen.getByRole('img').getAttribute('src')).toBe('/custom.png');
 });
 it('keeps a moving poster and retries after Safari refuses autoplay',async()=>{
  vi.spyOn(HTMLMediaElement.prototype,'play').mockRejectedValue(new DOMException('blocked','NotAllowedError'));
  const {container}=render(<ClipAvatar state="idle"/>);
  const video=container.querySelector('video')!;
  fireEvent.canPlay(video);
  await waitFor(()=>expect(container.querySelector('.jg-clip-avatar')).toHaveAttribute('data-motion','poster'));
  expect(container.querySelector('video')).toBe(video);
  fireEvent(window,new Event('pageshow'));
  await waitFor(()=>expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(2));
 });
 it('uses structured activity, not message content',()=>{
  const turn=session('pending').turns[0];
  turn.message='generate_image';
  expect(activityState(turn,true)).toBe('working');
  expect(activityState(undefined,false)).toBe('idle');
 });
});
describe('chat avatar lifecycle',()=>{
 it('latches completion across stream cleanup then expires',()=>{
  vi.useFakeTimers();
  const onState=vi.fn();
  const {rerender}=renderHook(({s,running})=>useChatAvatar(s,running,undefined,onState),{initialProps:{s:session('pending'),running:true}});
  expect(onState).toHaveBeenLastCalledWith('working');
  rerender({s:session('complete'),running:true});
  rerender({s:session('complete'),running:false});
  expect(onState).toHaveBeenLastCalledWith('milestone_level_up');
  act(()=>vi.advanceTimersByTime(4000));
  expect(onState).toHaveBeenLastCalledWith('idle');
 });
 it('does not celebrate historical or failed turns',()=>{
  const onState=vi.fn();
  const {rerender}=renderHook(({s})=>useChatAvatar(s,false,undefined,onState),{initialProps:{s:session('complete')}});
  expect(onState).toHaveBeenLastCalledWith('idle');
  rerender({s:session('pending')});
  rerender({s:session('failed')});
  expect(onState).toHaveBeenLastCalledWith('idle');
  expect(onState.mock.calls.flat()).not.toContain('milestone_level_up');
 });
 it('connection errors override activity',()=>{
  const onState=vi.fn();
  renderHook(()=>useChatAvatar(session('pending'),true,'offline',onState));
  expect(onState).toHaveBeenLastCalledWith('connecting');
 });
});
