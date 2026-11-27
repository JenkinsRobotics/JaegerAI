import { useEffect, useState, type FormEvent } from "react";

interface ToolEntry {
  name: string;
  description: string;
  tier: string;
  read_only: boolean;
  source: string;
  schema: Record<string, unknown>;
}

interface ToolCatalog {
  sources: Array<{ path: string; label: string }>;
  slash_commands: Array<{ name: string; description: string; surface: string }>;
}

interface SourceFile {
  path: string;
  source: string;
  revision: string | null;
}

const customRoot = "packages/jaeger-tools/src/jaeger_tools/custom";
const categoryOrder = ["Files & code", "Memory & workflows", "Web & media", "Devices & applications", "Integrations", "Runtime & other"];

function category(tool: ToolEntry) {
  if (tool.source.startsWith("mcp")) return "Integrations";
  if (/^(shell|read_file|write_file|edit_file|apply_patch|glob|search_files|repo_map)$/.test(tool.name)) return "Files & code";
  if (/^(memory_|workflow_|persistent_goals)/.test(tool.name)) return "Memory & workflows";
  if (/^(web_|youtube_|media_)/.test(tool.name)) return "Web & media";
  if (/^(droid_|minecraft_|jp01_|avatar_|list_mailboxes|batch_move_mail)/.test(tool.name)) return "Devices & applications";
  return "Runtime & other";
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Gateway returned HTTP ${response.status}.`);
  return result as T;
}

function SourceEditor({ baseUrl, sources, onSaved }: {
  baseUrl: string;
  sources: ToolCatalog["sources"];
  onSaved: () => void;
}) {
  const [opened, setOpened] = useState<SourceFile>();
  const [content, setContent] = useState("");
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const dirty = opened !== undefined && content !== opened.source;

  async function open(path: string) {
    setPending(true);
    setMessage("");
    setError("");
    try {
      const result = await request<SourceFile>(`${baseUrl}/v1/tools/source?path=${encodeURIComponent(path)}`);
      setOpened(result);
      setContent(result.source);
      setCreating(false);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Unable to open the source file.");
    } finally {
      setPending(false);
    }
  }

  function startNew(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!/^[a-z][a-z0-9_]{0,63}$/.test(newName)) return;
    const source = `"""Implement the ${newName} tool here."""\n\nfrom jaeger_contracts import ToolResult\n\n\ndef ${newName}(arguments: dict) -> ToolResult:\n    return ToolResult(tool_name="${newName}", ok=False, error="Not implemented")\n`;
    setOpened({ path: `${customRoot}/${newName}.py`, source, revision: null });
    setContent(source);
    setCreating(false);
    setError("");
    setMessage("");
  }

  async function save() {
    if (!opened) return;
    setPending(true);
    setMessage("");
    setError("");
    try {
      const result = await request<SourceFile>(`${baseUrl}/v1/tools/source`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...opened, source: content }),
      });
      setOpened(result);
      setContent(result.source);
      setMessage("Saved to the repository. Python syntax check passed.");
      onSaved();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Unable to save the source file.");
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="jg-card jg-tools-editor" aria-labelledby="tool-editor-heading">
      <h2 id="tool-editor-heading">Tool source editor</h2>
      <p className="jg-muted">Edits save to the checkout. New modules need registry wiring. Run tests before activating changes with a Gateway restart.</p>
      <div className="jg-tools-controls">
        <label>
          Source file
          <select className="jg-input" value={opened?.revision ? opened.path : ""} disabled={dirty || pending}
            onChange={(event) => { if (event.target.value) void open(event.target.value); }}>
            <option value="" disabled>Select a source file</option>
            {sources.map((file) => <option key={file.path} value={file.path}>{file.label}</option>)}
          </select>
        </label>
        <button type="button" className="jg-btn" disabled={dirty || pending} onClick={() => setCreating((value) => !value)}>
          New tool module
        </button>
      </div>
      {creating && (
        <form className="jg-tools-controls" onSubmit={startNew}>
          <label>Module name
            <input className="jg-input" value={newName} onChange={(event) => setNewName(event.target.value)}
              placeholder="my_tool" required pattern="[a-z][a-z0-9_]{0,63}" maxLength={64} />
          </label>
          <button className="jg-btn" type="submit">Create scaffold</button>
        </form>
      )}
      {opened && (
        <>
          <label className="jg-tools-editor-label" htmlFor="tool-source"><code>{opened.path}</code></label>
          <textarea id="tool-source" className="jg-input jg-tool-code" value={content} spellCheck={false}
            onChange={(event) => setContent(event.target.value)} disabled={pending} rows={16} />
          <div className="jg-tools-controls">
            <button type="button" className="jg-btn jg-btn-primary" disabled={pending || (!dirty && opened.revision !== null)}
              onClick={() => void save()}>{pending ? "Working…" : "Save to repository"}</button>
            <button type="button" className="jg-btn" disabled={pending || !dirty}
              onClick={() => { setContent(opened.source); setError(""); }}>Discard changes</button>
            {opened.revision && <button type="button" className="jg-btn" disabled={pending || dirty}
              onClick={() => void open(opened.path)}>Reload source</button>}
          </div>
        </>
      )}
      {message && <p role="status">{message}</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}

export function ToolsPage({ baseUrl }: { baseUrl: string }) {
  const [tools, setTools] = useState<ToolEntry[]>([]);
  const [catalog, setCatalog] = useState<ToolCatalog>({ sources: [], slash_commands: [] });
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState("all");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    void Promise.all([
      request<{ tools: ToolEntry[] }>(`${baseUrl}/v1/tools`, { signal: controller.signal }),
      request<ToolCatalog>(`${baseUrl}/v1/tools/catalog`, { signal: controller.signal }),
    ]).then(([inventory, details]) => {
      setTools(inventory.tools);
      setCatalog(details);
    }).catch((failure: unknown) => {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Unable to load tools.");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [baseUrl]);

  const term = query.trim().toLowerCase();
  const visible = tools.filter((tool) => (
    (mode === "all" || (mode === "read" ? tool.read_only : !tool.read_only)) &&
    `${tool.name} ${tool.description} ${tool.source} ${category(tool)}`.toLowerCase().includes(term)
  )).sort((a, b) => a.name.localeCompare(b.name));
  const commands = catalog.slash_commands.filter((command) => `${command.name} ${command.description}`.toLowerCase().includes(term));

  return (
    <div className="jg-content jg-workspace-page jg-tools-page">
      <header className="jg-tools-heading">
        <h1>Tools</h1>
        <a href="#tool-editor-heading" className="jg-btn">Open source editor</a>
      </header>
      <div className="jg-tools-controls">
        <label>Search tools and commands
          <input className="jg-input" type="search" value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
        <label>Access
          <select className="jg-input" value={mode} onChange={(event) => setMode(event.target.value)}>
            <option value="all">All access levels</option>
            <option value="read">Read only</option>
            <option value="actions">Action tools</option>
          </select>
        </label>
      </div>
      {loading && <p role="status">Loading the Gateway tool registry…</p>}
      {error && <p role="alert">{error}</p>}
      <section aria-labelledby="registered-tools-heading">
        <h2 id="registered-tools-heading">Registered tools <span className="jg-muted">({visible.length} of {tools.length})</span></h2>
        {!loading && !visible.length && <p className="jg-muted">No tools match the current filters.</p>}
        {categoryOrder.map((group) => {
          const entries = visible.filter((tool) => category(tool) === group);
          if (!entries.length) return null;
          return (
            <section key={group}>
              <h3>{group}</h3>
              <ul className="jg-tools-list">
                {entries.map((tool) => (
                  <li key={tool.name}>
                    <details>
                      <summary>
                        <code>{tool.name}</code>
                        <span className="jg-muted">{tool.source}</span>
                        <span className="jg-pill">{tool.read_only ? "Read only" : tool.tier.replaceAll("_", " ")}</span>
                      </summary>
                      <p>{tool.description}</p>
                      <pre aria-label={`${tool.name} input schema`}>{JSON.stringify(tool.schema, null, 2)}</pre>
                    </details>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </section>
      <section aria-labelledby="slash-commands-heading">
        <h2 id="slash-commands-heading">Slash commands</h2>
        <p className="jg-muted">These commands run in Terminal Chat.</p>
        <ul className="jg-tools-list">
          {commands.map((command) => (
            <li key={command.name} className="jg-tool-command">
              <code>{command.name}</code><span>{command.description}</span>
            </li>
          ))}
        </ul>
        {!loading && !commands.length && <p className="jg-muted">No slash commands match the search.</p>}
      </section>
      <SourceEditor baseUrl={baseUrl} sources={catalog.sources} onSaved={() => {
        void request<ToolCatalog>(`${baseUrl}/v1/tools/catalog`).then(setCatalog)
          .catch((failure: unknown) => setError(failure instanceof Error ? failure.message : "Unable to refresh the source catalog."));
      }} />
    </div>
  );
}
