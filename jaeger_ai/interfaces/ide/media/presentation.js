(function exposePresentation(root) {
'use strict';
// Presentation rules only — no Gateway/VS Code calls. Ported from the Mac
// app's ChatPresentation.swift and ToolCommandGroupView.swift (same product,
// same rules, JavaScript instead of Swift because a webview can't run
// Swift). Pure functions, unit-tested directly from Node.

function modelLabel(model) {
  const name = String(model || '').trim();
  return name || 'Choose model';
}

// MCP tool names carry a transport/server prefix (mcp__server__tool); keep
// only the actual tool name, and make underscores readable.
function toolName(raw) {
  const value = String(raw || '');
  const name = value.startsWith('mcp__') ? (value.split('__').pop() || value) : value;
  return name.replace(/_/g, ' ');
}

// "Using X" while running, "Used X" / "Used N tools" once settled — the
// same wording ToolCommandGroupView shows in the Mac app.
function activityTitle(items, running) {
  if (!items.length) return running ? 'Working' : 'Activity';
  if (items.length === 1) return `${running ? 'Using' : 'Used'} ${toolName(items[0].name)}`;
  return `${running ? 'Using' : 'Used'} ${items.length} tools`;
}

function activitySummary(items, running) {
  const phrases = items.map(item => {
    const name = String(item.name || '');
    if (/^(file_read|read_file|read|list_skill_dir|search_files)$/.test(name)) return running ? 'Reading files' : 'Read files';
    if (/^(file_write|write_file|edit_file|append_file|delete_file|apply_patch|patch|move_file|copy_file)$/.test(name)) return running ? 'Editing files' : 'Edited files';
    if (/^(exec_command|run_command|shell|terminal|execute_command)$/.test(name)) return running ? 'Running commands' : 'Ran commands';
    if (name.startsWith('mcp__')) return `${running ? 'Using' : 'Used'} ${name.split('__')[1].replace(/_/g, ' ')} integration`;
    return `${running ? 'Using' : 'Used'} ${toolName(name)}`;
  });
  return [...new Set(phrases)].map((phrase, index) => index ? phrase[0].toLowerCase() + phrase.slice(1) : phrase).join(', ');
}

// Mixed activity uses the same cursor/click mark as computer integrations.
// Inspect tool names, never prose arguments (which may mention unrelated tools).
function activityIcon(items) {
  const kinds = new Set(items.map(item => {
    const name = String(item.name || '').split('__').pop();
    if (/^(file_read|read_file|read|list_skill_dir|search_files)$/.test(name)) return 'read';
    if (/^(file_write|write_file|edit_file|append_file|delete_file|apply_patch|patch|move_file|copy_file)$/.test(name)) return 'edit';
    if (/^(exec_command|run_command|shell|terminal|execute_command)$/.test(name)) return 'tool';
    return 'integration';
  }));
  return kinds.size === 1 ? [...kinds][0] : 'integration';
}

function groupWorkRows(rows) {
  const result = [];
  for (const row of rows) {
    if (row.kind !== 'tool') { result.push(row); continue; }
    let group = result.at(-1);
    if (group?.kind !== 'tool-group') {
      group = { key: `group:${row.key}`, kind: 'tool-group', items: [], live: false };
      result.push(group);
    }
    group.items.push(row); group.live ||= row.phase === 'running';
  }
  return result;
}

function diffLines(diff) {
  let oldLine = 0, newLine = 0, inHunk = false;
  return String(diff || '').split('\n').flatMap(text => {
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(text);
    if (hunk) { inHunk = true; oldLine = Number(hunk[1]); newLine = Number(hunk[2]); return [{ kind: 'hunk', text }]; }
    if (!inHunk) return [];
    if (text.startsWith('+')) return [{ kind: 'addition', oldLine: '', newLine: newLine++, text: text.slice(1) }];
    if (text.startsWith('-')) return [{ kind: 'deletion', oldLine: oldLine++, newLine: '', text: text.slice(1) }];
    if (text.startsWith(' ')) return [{ kind: 'context', oldLine: oldLine++, newLine: newLine++, text: text.slice(1) }];
    return [];
  });
}

// One group per uninterrupted run of tool-shaped activity events — split
// whenever a non-tool event (anything without a `name`, e.g. a status
// marker) appears between them. Mirrors ToolCommandGroupView's doc comment:
// "one section per uninterrupted run of tool calls". An empty group never
// appears in the result, so a caller can render nothing when there is
// nothing to group — no placeholder "Activity" section with zero children.
function groupActivity(events) {
  const groups = [];
  let current = null;
  for (const event of events || []) {
    if (!event || !event.name) { current = null; continue; }
    if (!current) { current = []; groups.push(current); }
    current.push(event);
  }
  return groups;
}

// Failures stay countable while a group is collapsed — the one thing worth
// surfacing from activity the operator can't currently see into.
function failureCount(items) {
  return (items || []).filter(item => item && item.ok === false && !item.isStreaming).length;
}

// The operator-facing word for each state a turn can be in. Kept as one
// function so every surface (status line, conversation list, tab title)
// says the same thing for the same state.
function statusLabel({ connected, busy, pendingApprovalCount = 0, lastStatus }) {
  if (!connected) return 'Not connected';
  if (pendingApprovalCount > 0 || lastStatus === 'approval') return 'Waiting for your approval';
  if (lastStatus === 'blocked') return 'Blocked';
  if (lastStatus === 'quota') return 'Quota exceeded';
  if (lastStatus === 'auth') return 'Authentication required';
  if (lastStatus === 'unknown') return 'Unknown status';
  if (busy) return 'Working';
  if (lastStatus === 'cancelled') return 'Cancelled';
  if (lastStatus === 'failed' || lastStatus === 'execution_unknown') return 'Failed';
  if (lastStatus === 'completed') return 'Completed';
  return 'Connected';
}


// Chronological transcript, grouped by turn: a user message starts a new
// turn, and every assistant message until the next user message belongs to
// it. A leading assistant-only message (a welcome line with no prior user
// turn) becomes its own turn rather than being dropped. Pure — no DOM — so
// the transcript's shape is unit-tested independently of how it's drawn.
function groupTurns(messages) {
  const turns = [];
  let current = null;
  for (const message of messages || []) {
    if (!message || (message.role !== 'user' && message.role !== 'assistant')) continue;
    if (message.role === 'user' || !current) {
      current = { user: message.role === 'user' ? message : null, assistants: [] };
      turns.push(current);
      if (message.role === 'assistant') current.assistants.push(message);
    } else {
      current.assistants.push(message);
    }
  }
  return turns;
}

// Composite picker option value that encodes both provider and model ID,
// keeping options distinguishable when two providers offer the same model ID.
function providerModelValue(provider, id) {
  const routed = parseProviderModel(id);
  if (routed.provider === provider) id = routed.model;
  return `${provider}::${id}`;
}

// Parse a providerModelValue back to its parts. Returns empty strings for the
// 'Gateway default' sentinel (empty composite).
function parseProviderModel(value) {
  let s = String(value || '');
  if (s.startsWith('@')) {
    const colon = s.indexOf(':');
    if (colon > 1) return { provider: s.slice(1, colon), model: s.slice(colon + 1) };
    s = s.slice(1);
  }
  const sep = s.indexOf('::');
  if (sep === -1) return { provider: '', model: s };
  return { provider: s.slice(0, sep), model: s.slice(sep + 2) };
}

// Which provider/model rows a picker should offer, from the Gateway's
// authoritative /v1/runtime/models shape — never a hardcoded list. A model
// is offered only when it is both available and the provider itself is
// reachable; an unusable row would let the operator pick something that
// fails admission immediately after.
function selectableModels(catalog) {
  const rows = [];
  const seen = new Set();
  const addRow = (provider, id) => {
    provider = String(provider || '').trim();
    id = String(id || '').trim();
    if (id.startsWith('@')) { const routed = parseProviderModel(id); provider = routed.provider || provider; id = routed.model; }
    if (!id) return;
    const key = `${provider}::${id}`;
    if (seen.has(key)) return;
    seen.add(key);
    rows.push({ provider, id });
  };

  const providers = (catalog && Array.isArray(catalog.providers)) ? catalog.providers : [];
  for (const provider of providers) {
    if (!provider || !provider.reachable) continue;
    const providerId = provider.id || 'ollama';
    for (const model of provider.models || []) {
      if (!model || model.available === false) continue;
      const modelId = model.id || model.name;
      if (model.remote_host === 'cloud' && providerId === 'ollama') {
        addRow('ollama-cloud', modelId);
      }
      addRow(providerId, modelId);
    }
  }

  const rawGroups = (catalog && (Array.isArray(catalog.groups) ? catalog.groups : (catalog.webui_catalog && Array.isArray(catalog.webui_catalog.groups)) ? catalog.webui_catalog.groups : [])) || [];
  for (const group of rawGroups) {
    if (!group) continue;
    const isOnline = group.status
      ? group.status === 'online'
      : group.reachable !== false && group.credentials_available !== false;
    if (!isOnline) continue;
    const providerName = String(group.provider_id || group.provider || 'Other');
    const providerId = providerName.toLowerCase().replace(/\s+/g, '-') === 'ollama-cloud'
      ? 'ollama-cloud' : providerName;
    for (const model of group.models || []) {
      if (!model || model.available === false) continue;
      const modelId = model.id || model.name;
      addRow(providerId, modelId);
    }
  }

  return rows;
}

// Compare exact provider/model identities, never suffixes. A bare model may
// only be used when the catalog identifies one provider for it.
function modelSelectionAvailable(value, catalog) {
  const selected = parseProviderModel(value);
  if (!selected.model) return true;
  const matches = selectableModels(catalog)
    .map(row => parseProviderModel(providerModelValue(row.provider, row.id)))
    .filter(row => row.model === selected.model && (!selected.provider || row.provider === selected.provider));
  return matches.length > 0 && (Boolean(selected.provider) || new Set(matches.map(row => row.provider)).size === 1);
}

// Filter the Gateway-owned session projection by title, workspace, or ID.
// Group selectable catalog rows by provider. Preserves the Gateway's catalog
// order: providers appear in first-appearance order, models in catalog order.
function groupSelectableModels(rows) {
  const groups = new Map();
  for (const row of rows || []) {
    let key = row.provider || 'Other';
    if (key === 'ollama-cloud') key = 'Ollama Cloud';
    else if (key === 'ollama') key = 'Ollama';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  return groups;
}

// The pill label for a picker selection. '' is the Gateway/session default,
// 'config' is the settings-configured model, anything else is `provider::model`.
function modelSelectionLabel(choice, { configuredModel, sessionModel, unavailable = false } = {}) {
  let label = '';
  if (choice === 'config') label = configuredModel || 'From settings';
  else if (choice) label = parseProviderModel(choice).model || choice;
  else label = sessionModel || 'Gateway default';
  return unavailable ? `${label} (Unavailable)` : label;
}

// The Gateway provides transcript-aware search; this remains a client-side
// filter as an immediate projection while the async result arrives.
function filterChats(sessions, query) {
  const value = String(query || '').trim().toLowerCase();
  const rows = Array.isArray(sessions) ? sessions : [];
  if (!value) return rows;
  return rows.filter(session => {
    if (session?.search_match) return true;
    const title = String(session?.title || '').toLowerCase();
    const workspace = String(session?.workspace || '').toLowerCase();
    const id = String(session?.session_id || '').toLowerCase();
    return title.includes(value) || workspace.includes(value) || id.includes(value);
  });
}

const exportsObject = {
  modelLabel, toolName, activityTitle, activitySummary, activityIcon, groupWorkRows, diffLines, groupActivity, failureCount, statusLabel,
  groupTurns, selectableModels, providerModelValue, parseProviderModel, filterChats,
  groupSelectableModels, modelSelectionLabel, modelSelectionAvailable,
};
if (typeof module !== 'undefined') module.exports = exportsObject;
if (root) root.JaegerPresentation = exportsObject;
})(typeof window !== 'undefined' ? window : null);
