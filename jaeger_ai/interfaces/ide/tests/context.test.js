'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const commands = require('../commands');
const { parse } = require('../media/slash-commands');

const readMedia = name => fs.readFileSync(path.join(__dirname, '..', 'media', name), 'utf8');

test('/diagnostics maps to a real extension-host command', () => {
  const parsed = parse('/diagnostics', {});
  assert.equal(parsed.command.name, 'diagnostics');
  assert.equal(parsed.command.needs.length, 0);
});

test('diagnostics snapshot resolves workspace roots inside its own scope', () => {
  const extension = fs.readFileSync(path.join(__dirname, '..', 'extension.js'), 'utf8');
  const start = extension.indexOf('const diagnosticsSnapshot =');
  const body = extension.slice(start, extension.indexOf('const ideContext =', start));
  assert.match(body, /const roots = \(vscode\.workspace\.workspaceFolders/);
});

test('IDE startup targets the canonical Gateway daemon, not stack bootstrap or the macOS app', () => {
  const extension = fs.readFileSync(path.join(__dirname, '..', 'extension.js'), 'utf8');
  assert.match(extension, /const daemonArgs = \['gateway', 'daemon'\]/);
  assert.match(extension, /jaeger_ai\.core\.gateway\.server/);
  assert.doesNotMatch(extension, /stack', 'up/);
  assert.match(extension, /await ensureGatewayDaemon\(controller\.gateway\)/);
});

test('Gateway auto-start is an opt-in user setting, off by default', () => {
  const extension = fs.readFileSync(path.join(__dirname, '..', 'extension.js'), 'utf8');
  const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8'));
  const setting = pkg.contributes.configuration.properties['jaeger.autoStartGateway'];
  assert.equal(setting.default, false);
  assert.equal(setting.scope, 'application');
  const calls = extension.match(/ensureGatewayDaemon\(controller\.gateway\)/g) || [];
  assert.equal(calls.length, 1);
  assert.match(extension, /if \(userSetting\('autoStartGateway'\) === true\) await ensureGatewayDaemon\(controller\.gateway\)/);
});

test('testCommand is user-scoped so a workspace cannot choose a shell command', () => {
  const extension = fs.readFileSync(path.join(__dirname, '..', 'extension.js'), 'utf8');
  const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8'));
  assert.equal(pkg.contributes.configuration.properties['jaeger.testCommand'].scope, 'application');
  assert.match(extension, /const configured = userSetting\('testCommand'\)/);
  assert.doesNotMatch(extension, /getConfiguration\('jaeger'\)\.get\('testCommand'\)/);
  const body = extension.slice(extension.indexOf('function userSetting('), extension.indexOf('function detectTestRunner('));
  assert.match(body, /\.inspect\(key\)/);
  assert.match(body, /info\.globalValue/);
  assert.doesNotMatch(body, /workspaceValue|workspaceFolderValue/);
});

test('diagnosticsLines summarize and bound workspace problems', () => {
  const snapshot = {
    count: 3,
    truncated: false,
    diagnostics: [
      { severity: 'error', path: 'src/one.py', line: 1, message: 'Undefined name: foo' },
      { severity: 'warning', path: 'src/two.py', line: 9, message: 'Unused import os' },
      { severity: 'info', path: 'README.md', line: 1, message: 'Missing description' },
    ],
  };
  const lines = commands.diagnosticsLines(snapshot);
  assert.equal(lines[0], '3 problems · 1 errors, 1 warnings, 1 info/hints');
  assert.equal(lines.length, 4);
  assert.match(lines[1], /error · src\/one\.py:1 Undefined name: foo/);

  assert.deepEqual(commands.diagnosticsLines({ count: 0, diagnostics: [] }), ['No workspace problems reported.']);
  const truncated = commands.diagnosticsLines({ count: 20, truncated: true, diagnostics: [] });
  assert.match(truncated[0], /^20 problems/);
  assert.equal(truncated.at(-1), 'Output is bounded to 60 diagnostics.');
});

test('the IDE projects context chips from the existing ideContext contract', () => {
  const html = readMedia('index.html');
  const view = readMedia('view.js');
  const extension = readMedia('../extension.js');
  assert.match(html, /id="context-chips"/);
  assert.match(view, /renderContextChips\(\)/);
  assert.match(view, /context\.active_file/);
  assert.match(view, /context\.open_files/);
  assert.match(view, /post\('info', \{ what: 'diagnostics' \}\)/);
  assert.match(extension, /postContext\(\)/);
  assert.match(extension, /ideContext\(\), diagnostics: diagnosticsSnapshot\(\)\.count/);
});
