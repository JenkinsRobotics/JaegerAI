(function exposeSlash(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.JaegerSlash = api;
})(typeof window !== 'undefined' ? window : globalThis, () => {
'use strict';
// Slash commands for the composer: which exist, which are usable right now, and
// how typed text maps to one. Pure — no DOM, no VS Code. A command is listed only
// when a real Gateway/extension capability backs it; nothing here is decorative.

// needs: facts about the current conversation that must be true (see availability()).
const COMMANDS = [
  { name: 'new', group: 'Chat', description: 'Start a new conversation', needs: [] },
  { name: 'resume', group: 'Chat', description: 'Switch to another conversation', needs: [] },
  { name: 'rename', group: 'Chat', description: 'Rename this conversation', args: '<title>', takesArgs: true, needs: ['session'] },
  { name: 'stop', group: 'Chat', description: 'Stop the current turn', needs: ['busy'] },
  { name: 'copy', group: 'Chat', description: 'Copy the last answer', needs: ['answer'] },
  { name: 'export', group: 'Chat', description: 'Save this conversation as Markdown', needs: ['session'] },
  { name: 'model', group: 'Settings', description: 'Choose the model', needs: [] },
  { name: 'plan', group: 'Code', description: 'Plan this request without executing changes', args: '<request>', takesArgs: true, needs: [] },
  { name: 'diff', group: 'Code', description: 'Review the files this turn changed', needs: ['changes'] },
  { name: 'status', group: 'Info', description: 'Show connection, model and conversation status', needs: [] },
  { name: 'skills', group: 'Info', description: 'Browse available skills', args: '[filter]', takesArgs: true, needs: [] },
  { name: 'agent', group: 'Info', description: 'Show background agents and tasks', aliases: ['ps'], needs: [] },
];

const byName = new Map();
for (const command of COMMANDS) {
  byName.set(command.name, command);
  for (const alias of command.aliases || []) byName.set(alias, command);
}

function isAvailable(command, context) {
  return command.needs.every(need => Boolean(context?.[need]));
}

// Commands to offer while the user is typing the command word (first token, no
// space yet). Prefix matches come before substring matches; unusable ones are hidden.
function match(text, context) {
  const value = String(text || '');
  if (!value.startsWith('/') || /[\s]/.test(value)) return [];
  const token = value.slice(1).toLowerCase();
  const usable = COMMANDS.filter(command => isAvailable(command, context));
  const names = command => [command.name, ...(command.aliases || [])];
  const prefix = usable.filter(command => names(command).some(name => name.startsWith(token)));
  const inside = usable.filter(command => !prefix.includes(command)
    && (names(command).some(name => name.includes(token)) || command.description.toLowerCase().includes(token)));
  return [...prefix, ...inside];
}

// The command a submitted message means, or null when it is an ordinary message.
// Anything not exactly a known, usable command is sent as text — a leading "/"
// is legitimate in a prompt (paths, regexes), so we never swallow it.
function parse(text, context) {
  const hit = /^\/([A-Za-z][\w-]*)(?:[ \t]+([\s\S]*))?$/.exec(String(text || '').trim());
  if (!hit) return null;
  const command = byName.get(hit[1].toLowerCase());
  if (!command || !isAvailable(command, context)) return null;
  const args = (hit[2] || '').trim();
  if (args && !command.takesArgs) return null;
  return { command, args };
}

return { COMMANDS, match, parse, isAvailable };
});
