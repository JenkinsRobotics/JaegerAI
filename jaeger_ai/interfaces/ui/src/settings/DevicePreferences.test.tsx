import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {afterEach, expect, it, vi} from 'vitest';
import {DevicePreferencesPanel} from './DevicePreferencesPanel';
import {DEFAULT_DEVICE_PREFERENCES, DEVICE_PREF_KEY, applyDevicePreferences, devicePreferenceSnapshot, displayDate, displayDayDistance, saveDevicePreferences} from './devicePreferences';
import {MinimalChat, needsSeparator, separatorLabel} from '../chat/MinimalChat';
import {useStreamStyle} from '../chat/streamStyle';
import type {ChatHost} from '../chat/host';
(globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => {vi.restoreAllMocks(); vi.unstubAllGlobals(); for(const key of Object.keys(localStorage)) if(key.startsWith(DEVICE_PREF_KEY)) localStorage.removeItem(key); applyDevicePreferences(DEFAULT_DEVICE_PREFERENCES);});
const fill = async (element: HTMLElement, label: string, value: string) => {
  const field = element.querySelector<HTMLInputElement | HTMLSelectElement>(`[aria-label="${label}"]`)!;
  await act(async () => {Object.getOwnPropertyDescriptor(field instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(field, value); field.dispatchEvent(new Event(field instanceof HTMLSelectElement ? 'change' : 'input', {bubbles: true}));});
};
it('uses the selected display timezone consistently for day labels across midnight and DST', () => {
  saveDevicePreferences({...DEFAULT_DEVICE_PREFERENCES, timeZone: 'America/Los_Angeles', dateLocale: 'en-GB'});
  const before = Date.parse('2026-03-09T06:59:00Z'), after = Date.parse('2026-03-09T07:01:00Z');
  expect(displayDayDistance(before, after)).toBe(1);
  expect(needsSeparator(before, after)).toBe(true);
  expect(separatorLabel(before, after)).toContain('Yesterday');
  expect(displayDate(before, {year:'numeric', month:'2-digit', day:'2-digit'})).toBe('08/03/2026');
  expect(devicePreferenceSnapshot().preferences.timeZone).toBe('America/Los_Angeles');
  expect(() => saveDevicePreferences({...DEFAULT_DEVICE_PREFERENCES, timeZone: 'Not/A_Real_Zone'})).toThrow();
  expect(devicePreferenceSnapshot().preferences.timeZone).toBe('America/Los_Angeles');
});
it('preserves malformed originals and refuses to claim/apply persistence on storage failure', () => {
  localStorage.setItem(DEVICE_PREF_KEY, 'original-invalid-settings');
  expect(devicePreferenceSnapshot().error).toBeTruthy();
  expect(localStorage.getItem(DEVICE_PREF_KEY)).toBe('original-invalid-settings');
  saveDevicePreferences(DEFAULT_DEVICE_PREFERENCES);
  const backup = Object.keys(localStorage).find(key => key.startsWith(DEVICE_PREF_KEY + '.recovery.'))!;
  expect(localStorage.getItem(backup)).toBe('original-invalid-settings');
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {throw Error('Storage blocked');});
  expect(() => saveDevicePreferences({...DEFAULT_DEVICE_PREFERENCES, motion:'reduce'})).toThrow('Storage blocked');
  expect(document.documentElement.dataset.jgMotion).toBe('system');
});
it('applies spelling and actual reveal reduction without losing the owned composer draft or sending work', async () => {
  const source = {capabilities:{voice:false}, startTurn:vi.fn(), sessions:{load:vi.fn(async () => ({id:'owned-preferences',title:'Owned',turns:[]}))}} as unknown as ChatHost;
  function StyleProbe() {const style = useStreamStyle(); return <output aria-label="Actual reveal policy">{style.reveal.mode}/{style.enter.kind}/{String(style.scroll.smooth)}</output>;}
  const element=document.createElement('div'); document.body.append(element); const root=createRoot(element);
  await act(async () => root.render(<><DevicePreferencesPanel/><StyleProbe/><MinimalChat host={source} sessionId="owned-preferences"/></>));
  const composer=element.querySelector<HTMLTextAreaElement>('[aria-label="Message"]')!;
  await act(async () => {Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(composer,'Unsent owned draft'); composer.dispatchEvent(new Event('input',{bubbles:true}));});
  await fill(element,'Motion preference','reduce');
  await act(async () => element.querySelector<HTMLInputElement>('[aria-label="Composer spellcheck"]')!.click());
  await act(async () => [...element.querySelectorAll('button')].find(b=>b.textContent==='Save device preferences')!.click());
  expect(composer.value).toBe('Unsent owned draft');
  expect(composer.getAttribute('spellcheck')).toBe('false');
  expect(element.querySelector('output')?.textContent).toBe('raw/none/false');
  expect(document.documentElement.dataset.jgMotion).toBe('reduce');
  expect(source.startTurn).not.toHaveBeenCalled();
  expect(source.sessions.load).toHaveBeenCalledTimes(1);
  await act(async()=>root.unmount());
  const next=createRoot(element); await act(async()=>next.render(<DevicePreferencesPanel/>));
  expect(element.querySelector<HTMLInputElement>('[aria-label="Composer spellcheck"]')!.checked).toBe(false);
  await act(async()=>next.unmount()); element.remove();
});
it('honors system reduction even when the saved preference follows system', async () => {
  vi.stubGlobal('matchMedia', () => ({matches:true, addEventListener:vi.fn(), removeEventListener:vi.fn()}));
  function Probe() {const style=useStreamStyle(); return <output>{style.reveal.mode}/{style.enter.kind}</output>;}
  const element=document.createElement('div'); const root=createRoot(element);
  await act(async()=>root.render(<Probe/>)); expect(element.textContent).toBe('raw/none');
  await act(async()=>root.unmount());
});
it('shows validation failure and keeps the unsaved display settings text', async () => {
  const element=document.createElement('div'); const root=createRoot(element);
  await act(async()=>root.render(<DevicePreferencesPanel/>)); await fill(element,'Display timezone','Not/A_Real_Zone');
  await act(async()=>element.querySelector('button')!.click());
  expect(element.querySelector<HTMLInputElement>('[aria-label="Display timezone"]')!.value).toBe('Not/A_Real_Zone');
  expect(element.textContent).toContain('Not saved:'); expect(element.textContent).not.toContain('Applied now');
  expect(localStorage.getItem(DEVICE_PREF_KEY)).toBeNull();
  await act(async()=>root.unmount());
});
