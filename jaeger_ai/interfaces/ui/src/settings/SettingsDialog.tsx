/* Settings (⌘, or the account chip): Chat → Stream style. The choice is stored per device and applies to
 * every open chat at once (streamStyle.ts). */
import { Dialog } from "@aether/ui";
import { setStreamStyle, STREAM_STYLE_IDS, STREAM_STYLE_LABELS, useStreamStyle } from "../chat/streamStyle";

const HINT: Record<string, string> = {
  grok: "Words flow in with a soft fade, like Grok.",
  instant: "Text appears exactly as it arrives, no smoothing.",
};

export function SettingsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const current = useStreamStyle().id;
  return (
    <Dialog open={open} title="Settings" onClose={onClose} actions={<button type="button" className="aui-button" onClick={onClose}>Done</button>}>
      <section className="jg-settings">
        <h3 className="jg-settings__heading">Chat</h3>
        <fieldset className="jg-settings__group">
          <legend className="jg-settings__label">Stream style</legend>
          {STREAM_STYLE_IDS.map((id) => (
            <label key={id} className={`jg-settings__option${id === current ? " is-selected" : ""}`}>
              <input type="radio" name="stream-style" value={id} checked={id === current} onChange={() => setStreamStyle(id)} />
              <span className="jg-settings__name">{STREAM_STYLE_LABELS[id]}</span>
              {HINT[id] && <span className="jg-settings__hint">{HINT[id]}</span>}
            </label>
          ))}
        </fieldset>
      </section>
    </Dialog>
  );
}
