/* Connect apps (spec §Connect Apps). Stub: the listed apps and their states
 * arrive with the CA endpoints. */
import { Dialog } from "@aether/ui";

const APPS = [
  { id: "vscode", name: "VS Code", note: "Jaeger IDE Chat extension" },
  { id: "github", name: "GitHub", note: "Repos, issues and PRs" },
  { id: "ollama", name: "Ollama", note: "Local models" },
];

export function ConnectAppsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} title="Connect apps" onClose={onClose} actions={<button type="button" className="aui-button" onClick={onClose}>Close</button>}>
      <ul className="jg-apps">
        {APPS.map((app) => (
          <li key={app.id} className="jg-apps__row">
            <span className="jg-avatar" style={{ width: 28, height: 28 }}><span className="jg-avatar__initials">{app.name.slice(0, 2)}</span></span>
            <span className="jg-agent-row__text"><span className="jg-agent-row__name">{app.name}</span><span className="jg-agent-row__preview">{app.note}</span></span>
            <button type="button" className="aui-button" disabled>Connect</button>
          </li>
        ))}
      </ul>
    </Dialog>
  );
}
