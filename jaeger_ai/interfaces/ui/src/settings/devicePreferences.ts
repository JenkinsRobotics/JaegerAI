/** Nonsecurity display preferences, owned by this browser/WK profile only. */
import {useEffect, useState} from 'react';
export const DEVICE_PREF_KEY = 'jaeger.ui.device-preferences.v1';
export const DEVICE_PREF_EVENT = 'jaeger-device-preferences';
export interface DevicePreferences {motion: 'system' | 'reduce'; spellcheck: boolean; timeZone: string; dateLocale: string}
export const DEFAULT_DEVICE_PREFERENCES: DevicePreferences = {motion: 'system', spellcheck: true, timeZone: 'system', dateLocale: 'system'};
export function validateDevicePreferences(value: unknown): DevicePreferences {
  if (!value || typeof value !== 'object') throw Error('Invalid device preferences; saved original retained');
  const p = value as DevicePreferences;
  if (Object.keys(p).sort().join(',') !== 'dateLocale,motion,spellcheck,timeZone' || !['system','reduce'].includes(p.motion) || typeof p.spellcheck !== 'boolean' || typeof p.timeZone !== 'string' || typeof p.dateLocale !== 'string' || p.timeZone.length > 100 || p.dateLocale.length > 100) throw Error('Unsupported device preferences');
  let timeZone = p.timeZone.trim(), dateLocale = p.dateLocale.trim();
  if (timeZone !== 'system') timeZone = new Intl.DateTimeFormat('en', {timeZone}).resolvedOptions().timeZone;
  if (dateLocale !== 'system') {
    dateLocale = Intl.getCanonicalLocales(dateLocale)[0];
    if (!dateLocale || !Intl.DateTimeFormat.supportedLocalesOf([dateLocale]).length) throw Error('Formatting locale unavailable on this device');
  }
  return {...p, timeZone, dateLocale};
}
let cachedRaw: string | null | undefined;
let cachedSnapshot: {preferences: DevicePreferences; error?: string} | undefined;
export function devicePreferenceSnapshot(): {preferences: DevicePreferences; error?: string} {
  try {
    const raw = localStorage.getItem(DEVICE_PREF_KEY);
    if (cachedSnapshot && raw === cachedRaw) return cachedSnapshot;
    cachedRaw = raw;
    try {cachedSnapshot = {preferences: raw ? validateDevicePreferences(JSON.parse(raw)) : {...DEFAULT_DEVICE_PREFERENCES}};}
    catch (e) {cachedSnapshot = {preferences: {...DEFAULT_DEVICE_PREFERENCES}, error: String(e)};}
    return cachedSnapshot;
  } catch (e) {return {preferences: {...DEFAULT_DEVICE_PREFERENCES}, error: String(e)};}
}
export function applyDevicePreferences(p: DevicePreferences) {
  document.documentElement.dataset.jgMotion = p.motion;
  document.documentElement.spellcheck = p.spellcheck;
}
export function saveDevicePreferences(value: DevicePreferences): DevicePreferences {
  const p = validateDevicePreferences(value);
  const prior = devicePreferenceSnapshot();
  const raw = localStorage.getItem(DEVICE_PREF_KEY);
  if (raw && prior.error) localStorage.setItem(DEVICE_PREF_KEY + '.recovery.' + crypto.randomUUID(), raw);
  // Failed storage must not claim persistence or apply a different live state.
  localStorage.setItem(DEVICE_PREF_KEY, JSON.stringify(p));
  applyDevicePreferences(p);
  window.dispatchEvent(new Event(DEVICE_PREF_EVENT));
  return p;
}
export function useDevicePreferences(): DevicePreferences {
  const [value, setValue] = useState(() => devicePreferenceSnapshot().preferences);
  useEffect(() => {
    const sync = () => setValue(devicePreferenceSnapshot().preferences);
    const storage = (e: StorageEvent) => {if (e.key === DEVICE_PREF_KEY || e.key === null) sync();};
    window.addEventListener(DEVICE_PREF_EVENT, sync); window.addEventListener('storage', storage);
    return () => {window.removeEventListener(DEVICE_PREF_EVENT, sync); window.removeEventListener('storage', storage);};
  }, []);
  return value;
}
export function useReducedMotion(): boolean {
  const prefs = useDevicePreferences();
  const [system, setSystem] = useState(() => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches);
  useEffect(() => {if (typeof matchMedia !== 'function') return; const media = matchMedia('(prefers-reduced-motion: reduce)'); const sync = () => setSystem(media.matches); media.addEventListener?.('change', sync); return () => media.removeEventListener?.('change', sync);}, []);
  return prefs.motion === 'reduce' || system;
}
const formatters = new Map<string, Intl.DateTimeFormat>();
function formatter(locale: string | undefined, options: Intl.DateTimeFormatOptions) {
  const key = JSON.stringify([locale, options]);
  let value = formatters.get(key);
  if (!value) {value = new Intl.DateTimeFormat(locale, options); if (formatters.size >= 32) formatters.delete(formatters.keys().next().value!); formatters.set(key, value);}
  return value;
}
export function displayDate(value: Date | number, options: Intl.DateTimeFormatOptions = {dateStyle: 'medium', timeStyle: 'medium'}): string {
  const date = value instanceof Date ? value : new Date(value);
  if (!Number.isFinite(date.getTime())) return 'Unknown time';
  const p = devicePreferenceSnapshot().preferences;
  return formatter(p.dateLocale === 'system' ? undefined : p.dateLocale, {...options, ...(p.timeZone !== 'system' ? {timeZone: p.timeZone} : {})}).format(date);
}
export function displayDayKey(value: number): string {
  const p = devicePreferenceSnapshot().preferences;
  const parts = formatter('en', {year: 'numeric', month: '2-digit', day: '2-digit', calendar: 'gregory', numberingSystem: 'latn', ...(p.timeZone !== 'system' ? {timeZone: p.timeZone} : {})}).formatToParts(new Date(value));
  return ['year','month','day'].map(key => parts.find(part => part.type === key)!.value).join('-');
}
export function displayDayDistance(earlier: number, later = Date.now()): number {
  return Math.round((Date.parse(displayDayKey(later)) - Date.parse(displayDayKey(earlier))) / 86400000);
}
