'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.join(__dirname, '..');
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
const packager = fs.readFileSync(path.join(root, 'package_extension.py'), 'utf8');
const hostModules = ['extension.js', 'conversation.js', 'gateway.js', 'commands.js'];

// A local require that is missing from the shipped file list only fails once the
// extension is installed (activation throws), so it is checked here.
test('every module the extension host requires ships in the package', () => {
  const required = new Set();
  for (const file of hostModules) {
    const source = fs.readFileSync(path.join(root, file), 'utf8');
    for (const [, target] of source.matchAll(/require\('\.\/([\w-]+)(?:\.js)?'\)/g)) {
      if (target !== 'contract') required.add(`${target}.js`); // contract.json is generated at build time
    }
  }
  assert.ok(required.has('commands.js'), 'sanity: the host requires commands.js');
  for (const file of required) {
    assert.ok(fs.existsSync(path.join(root, file)), `${file} does not exist`);
    assert.ok(manifest.files.includes(file), `${file} missing from package.json "files"`);
    assert.ok(packager.includes(`"${file}"`), `${file} missing from package_extension.py`);
  }
});

test('every script and stylesheet the panel loads is a media file that exists', () => {
  const html = fs.readFileSync(path.join(root, 'media', 'index.html'), 'utf8');
  const extension = fs.readFileSync(path.join(root, 'extension.js'), 'utf8');
  const placeholders = [...html.matchAll(/\{\{([A-Z_]+)\}\}/g)].map(m => m[1]).filter(k => !['CSP', 'NONCE'].includes(k));
  for (const key of new Set(placeholders)) {
    assert.ok(new RegExp(`\\b${key}\\b`).test(extension.split('html = html.replace')[1] || ''), `${key} not substituted by the extension`);
    const asset = new RegExp(`${key}: asset\\('([^']+)'\\)`).exec(extension)?.[1];
    if (asset && key !== 'SMD') assert.ok(fs.existsSync(path.join(root, 'media', asset)), `media/${asset} does not exist`);
  }
});
