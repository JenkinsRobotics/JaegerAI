'use strict';
// Walk every local require() reachable from package.json "main" and check the
// packaged file list contains it: a missing file only fails after install.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const root = path.join(__dirname, '..');
const manifest = require('../package.json');
const generated = new Set(['contract.json', 'build.json']); // written by package_extension.py

function requireGraph() {
  const seen = new Set(), queue = [path.normalize(manifest.main)];
  while (queue.length) {
    const file = queue.shift();
    if (seen.has(file)) continue;
    seen.add(file);
    if (!file.endsWith('.js')) continue;
    const source = fs.readFileSync(path.join(root, file), 'utf8');
    for (const [, spec] of source.matchAll(/require\(\s*'(\.{1,2}\/[^']+)'\s*\)/g)) {
      let target = path.normalize(path.join(path.dirname(file), spec));
      if (!path.extname(target) || !fs.existsSync(path.join(root, target))) {
        if (fs.existsSync(path.join(root, `${target}.js`))) target += '.js';
        else if (!generated.has(path.basename(target))) assert.fail(`${file} requires missing ${spec}`);
      }
      queue.push(target);
    }
  }
  return [...seen].sort();
}

// vsce and npm always ship package.json, whatever "files" says.
const covered = (file, patterns) => file === 'package.json' || patterns.some(p => p === file
  || (p.endsWith('/**') && file.startsWith(p.slice(0, -2))));

test('the shipped require graph reaches the chat panel and conversation.js', () => {
  const graph = requireGraph();
  for (const file of ['extension.js', 'chat-panel.js', 'conversation.js', 'native-turn.js', 'controller.js', 'copilot-bridge.js', 'gateway.js']) {
    assert.ok(graph.includes(file), `${file} not reachable from ${manifest.main}: ${graph}`);
  }
});

test('every file in the require graph is listed in package.json "files"', () => {
  for (const file of requireGraph()) assert.ok(covered(file, manifest.files), `${file} not in "files"`);
});

test('npm pack --dry-run ships every non-generated file in the require graph', { timeout: 120000 }, t => {
  const run = spawnSync('npm', ['pack', '--dry-run', '--json', '--ignore-scripts'], { cwd: root, encoding: 'utf8' });
  if (run.error || run.status !== 0) return t.skip(`npm pack unavailable: ${run.error?.message || run.stderr}`);
  const packed = new Set(JSON.parse(run.stdout)[0].files.map(f => f.path));
  for (const file of requireGraph().filter(f => !generated.has(path.basename(f)))) {
    assert.ok(packed.has(file), `${file} missing from npm pack`);
  }
});
