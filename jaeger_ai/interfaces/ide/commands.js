'use strict';
// Extension-host side of the slash commands: turns Gateway data into the small
// text the panel shows, and a conversation into Markdown. Pure functions so they
// can be tested without VS Code.

const clip = (text, max) => {
  const value = String(text ?? '').replace(/\s+/g, ' ').trim();
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
};

function statusLines({ version, session, model, endpoint }) {
  const lines = [];
  lines.push(`Gateway: ${version?.component || 'jaeger-gateway'} ${version?.version || ''}`.trim());
  if (endpoint) lines.push(`Endpoint: ${endpoint}`);
  lines.push(`Model: ${model || 'Gateway default'}`);
  if (session) {
    lines.push(`Conversation: ${clip(session.title || 'Untitled', 80)}`);
    lines.push(`Messages: ${Array.isArray(session.messages) ? session.messages.length : session.message_count ?? 0}`);
    if (session.workspace) lines.push(`Workspace: ${session.workspace}`);
    if (session.status) lines.push(`State: ${session.status}`);
  } else {
    lines.push('Conversation: none open');
  }
  return lines;
}

function skillLines(skills, query = '') {
  const rows = Array.isArray(skills) ? skills : [];
  if (!rows.length) return [query ? `No skills match “${query}”.` : 'No skills available.'];
  const groups = new Map();
  for (const skill of rows) {
    const list = groups.get(skill.category || 'general') || [];
    list.push(skill); groups.set(skill.category || 'general', list);
  }
  const lines = [`${rows.length} skill${rows.length === 1 ? '' : 's'}${query ? ` matching “${query}”` : ''}`];
  let shown = 0;
  for (const [category, list] of [...groups].sort((a, b) => b[1].length - a[1].length)) {
    lines.push(`${category} (${list.length}): ${list.slice(0, 6).map(skill => skill.name).join(', ')}${list.length > 6 ? ', …' : ''}`);
    if (++shown >= 12) { lines.push(`…and ${groups.size - shown} more categories. Add a word to filter, e.g. /skills pdf`); break; }
  }
  return lines;
}

function diagnosticsLines(snapshot = {}) {
  const rows = Array.isArray(snapshot.diagnostics) ? snapshot.diagnostics : [];
  const count = Number(snapshot.count ?? rows.length);
  if (!count) return ['No workspace problems reported.'];
  const errors = rows.filter(row => row.severity === 'error').length;
  const warnings = rows.filter(row => row.severity === 'warning').length;
  const infos = rows.filter(row => ['info', 'hint'].includes(row.severity)).length;
  const lines = [`${count} problem${count === 1 ? '' : 's'} · ${errors} errors, ${warnings} warnings, ${infos} info/hints`];
  for (const row of rows.slice(0, 12)) {
    lines.push(`${row.severity || 'info'} · ${clip(row.path || '', 80)}:${row.line || 1} ${clip(row.message || '', 140)}`);
  }
  if (count > rows.slice(0, 12).length) lines.push(`…and ${count - rows.slice(0, 12).length} more`);
  if (snapshot.truncated) lines.push('Output is bounded to 60 diagnostics.');
  return lines;
}

function parseWorktrees(porcelain = '') {
  const blocks = String(porcelain || '').trim().split(/\n\s*\n/).filter(Boolean);
  return blocks.map(block => {
    const fields = Object.fromEntries(block.split('\n').map(line => {
      const index = line.indexOf(' ');
      return index === -1 ? [line, ''] : [line.slice(0, index), line.slice(index + 1)];
    }));
    return {
      path: fields.worktree || '',
      head: fields.HEAD || '',
      branch: fields.branch ? fields.branch.replace(/^refs\/heads\//, '') : '',
      bare: fields.bare === '',
      detached: fields.detached === '',
    };
  }).filter(row => row.path && !row.bare);
}

function worktreeLines(rows) {
  const trees = Array.isArray(rows) ? rows : [];
  if (!trees.length) return ['No git worktrees found for the selected workspace.'];
  return trees.map(row => `${row.branch || row.head.slice(0, 12) || 'detached'} · ${row.path}`);
}

function taskLines(payload) {
  const tasks = Array.isArray(payload) ? payload : payload?.tasks || [];
  if (!tasks.length) return ['No background agents or tasks.'];
  return tasks.slice(0, 15).map(task => {
    const id = String(task.task_id || task.id || '').slice(0, 14);
    return `${task.status || 'unknown'} · ${clip(task.objective || task.title || id, 90)}${id ? ` (${id})` : ''}`;
  });
}

function slug(text) {
  return String(text || 'conversation').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48) || 'conversation';
}

function exportMarkdown(session) {
  const lines = [`# ${clip(session?.title || 'Conversation', 120)}`, ''];
  for (const message of session?.messages || []) {
    if (message.role !== 'user' && message.role !== 'assistant') continue;
    lines.push(`## ${message.role === 'user' ? 'You' : 'Jaeger'}`, '', String(message.content ?? '').trim(), '');
  }
  return `${lines.join('\n').trimEnd()}\n`;
}

// What the operator has open, in the shape the Gateway accepts (options.ide). Pure so
// it can be tested without VS Code: the host passes plain data in, this bounds it.
const IDE_LIMITS = { selection: 4000, openFiles: 12, folders: 5, path: 400 };

function buildIdeContext({ folders = [], active = null, openPaths = [] } = {}) {
  const roots = folders.map(String).filter(Boolean);
  const relative = file => {
    const value = String(file || '');
    const root = roots.find(r => value === r || value.startsWith(r.endsWith('/') ? r : `${r}/`));
    return (root ? value.slice(root.length).replace(/^\//, '') : value).slice(0, IDE_LIMITS.path);
  };
  const context = {};
  if (roots.length) context.workspace_folders = roots.slice(0, IDE_LIMITS.folders).map(r => r.slice(0, IDE_LIMITS.path));
  if (active?.path) {
    context.active_file = relative(active.path);
    if (active.language) context.language = String(active.language).slice(0, 40);
    if (Number(active.cursorLine) > 0) context.cursor_line = Number(active.cursorLine);
    const text = String(active.selectionText || '');
    if (text.trim()) {
      context.selection = { text: text.slice(0, IDE_LIMITS.selection), truncated: text.length > IDE_LIMITS.selection,
        start_line: Number(active.startLine) || 1, end_line: Number(active.endLine) || 1 };
    }
  }
  const seen = new Set(context.active_file ? [context.active_file] : []);
  const files = [];
  for (const path of openPaths) {
    const name = relative(path);
    if (name && !seen.has(name)) { seen.add(name); files.push(name); }
    if (files.length >= IDE_LIMITS.openFiles) break;
  }
  if (files.length) context.open_files = files;
  return Object.keys(context).length ? context : null;
}

module.exports = { statusLines, skillLines, taskLines, diagnosticsLines, exportMarkdown, slug, clip, buildIdeContext, parseWorktrees, worktreeLines, IDE_LIMITS };
