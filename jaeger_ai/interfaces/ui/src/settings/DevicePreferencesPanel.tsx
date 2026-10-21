import {useState} from 'react';
import {devicePreferenceSnapshot, saveDevicePreferences, type DevicePreferences} from './devicePreferences';
export function DevicePreferencesPanel() {
  const initial = devicePreferenceSnapshot();
  const [draft, setDraft] = useState<DevicePreferences>(initial.preferences);
  const [error, setError] = useState(initial.error), [notice, setNotice] = useState<string>();
  const update = (patch: Partial<DevicePreferences>) => {setDraft(d => ({...d,...patch})); setNotice(undefined);};
  const save = () => {try {setDraft(saveDevicePreferences(draft)); setError(undefined); setNotice('Saved on this device. Applied now; no app restart or server change.');} catch (e) {setError(String(e)); setNotice(undefined);}};
  return <section className="jg-device-preferences" aria-label="Device display preferences"><h3>Device display and input</h3>
    <p>These preferences belong to this browser or Mac profile. They do not sync to other devices or change bot context, permissions, model settings or scheduler timezones.</p>
    {error && <p role="alert">Not saved: {error}. Original preferences and draft retained.</p>}{notice && <p role="status">{notice}</p>}
    <label>Motion<select aria-label="Motion preference" value={draft.motion} onChange={e => update({motion: e.target.value as DevicePreferences['motion']})}><option value="system">Follow system</option><option value="reduce">Reduce motion</option></select></label>
    <p>System reduced motion is always respected, including streamed text reveal and smooth scrolling.</p>
    <label className="jg-device-check"><input type="checkbox" aria-label="Composer spellcheck" checked={draft.spellcheck} onChange={e => update({spellcheck: e.target.checked})}/>Composer spellcheck</label>
    <label>Formatting locale<input aria-label="Formatting locale" value={draft.dateLocale} placeholder="system or en-GB" onChange={e => update({dateLocale: e.target.value})}/></label>
    <label>Display timezone<input aria-label="Display timezone" value={draft.timeZone} placeholder="system or America/Los_Angeles" onChange={e => update({timeZone: e.target.value})}/></label>
    <button onClick={save}>Save device preferences</button>
    <dl><dt>Interface language</dt><dd>English. Date formatting does not install translations.</dd><dt>Native hardware acceleration</dt><dd>Managed by this host; no supported runtime toggle. Changing native launch configuration would require a separate build/relaunch.</dd><dt>Bot settings</dt><dd>Name, icon and knowledge belong to the existing agent registry; change them in Agents.</dd><dt>Shared operator settings</dt><dd>Providers, schedules, approvals and subscriptions belong to their existing Gateway owners.</dd><dt>Voice/camera and large avatars</dt><dd>Implementation remains paused.</dd></dl>
  </section>;
}
