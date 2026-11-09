'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const {
  catalogModelInformation,
  messageText,
  modelInformation,
  promptFromMessages,
  registerJaegerLanguageModelProvider,
  selectedModel,
} = require('../language-model-provider');

test('native model is owned by the Jaeger Gateway', () => {
  const info = modelInformation();
  assert.equal(info.id, 'jaeger-gateway');
  assert.equal(info.family, 'jaeger');
  assert.match(info.tooltip, /Gateway/);
});

test('language-model messages retain roles and text', () => {
  const messages = [
    { role: 1, content: [{ value: 'first question' }] },
    { role: 2, content: [{ value: 'first answer' }] },
    { role: 1, content: [{ value: 'follow up' }, { value: ' now' }] },
  ];
  assert.equal(messageText(messages[2]), 'follow up now');
  assert.equal(promptFromMessages(messages), [
    'User:\nfirst question',
    'Assistant:\nfirst answer',
    'User:\nfollow up now',
  ].join('\n\n'));
});

test('Gateway catalog becomes real selectable native models', () => {
  const models = catalogModelInformation({
    providers: [
      { id: 'ollama', display_name: 'Ollama', reachable: true, models: [
        { id: 'glm-5.3-flash:cloud', available: true, remote_host: 'cloud', context_length: 131072 },
        { id: 'local-model', available: true, context_length: 32768, capabilities: ['vision'] },
        { id: 'offline-model', available: false },
      ] },
      { id: 'down', reachable: false, models: [{ id: 'unreachable', available: true }] },
    ],
    active: { provider: 'ollama-cloud', model: 'glm-5.3-flash:cloud' },
  });

  assert.deepEqual(models.map(model => model.id), [
    'ollama-cloud::glm-5.3-flash:cloud',
    'ollama::local-model',
  ]);
  assert.equal(models[0].name, 'glm-5.3-flash:cloud');
  assert.equal(models[0].detail, 'Ollama Cloud via Jaeger Gateway');
  assert.equal(models[0].maxInputTokens, 131072);
  assert.equal(models[0].isDefault, true);
  assert.equal(models[1].isDefault, false);
  assert.equal(models[1].capabilities.imageInput, true);
});

test('web catalog is used when provider inventory is absent', () => {
  const models = catalogModelInformation({ webui_catalog: { groups: [
    { provider_id: 'openai', display_name: 'OpenAI', status: 'online', context_length: 128000,
      models: [{ id: 'gpt-5', available: true }] },
    { provider_id: 'anthropic', status: 'offline', models: [{ id: 'claude', available: true }] },
  ] } });
  assert.deepEqual(models.map(model => model.id), ['openai::gpt-5']);
  assert.equal(models[0].isDefault, true);
});

test('active Gateway runtime remains selectable when provider probes are empty', () => {
  const models = catalogModelInformation({
    providers: [{ id: 'ollama', reachable: false, models: [] }],
    active: { provider: 'cli', model: 'grok' },
    webui_catalog: { active_provider: 'cli', default_model: 'grok', groups: [] },
  });
  assert.deepEqual(models.map(model => model.id), ['cli::grok']);
  assert.equal(models[0].name, 'grok');
  assert.equal(models[0].detail, 'CLI Runtime via Jaeger Gateway');
  assert.equal(models[0].isDefault, true);
});

test('native selection overrides the legacy configured-model fallback', () => {
  const vscode = { workspace: { getConfiguration: () => ({ get: () => 'openai::configured' }) } };
  assert.deepEqual(selectedModel({ id: 'ollama-cloud::chosen' }, vscode),
    { provider: 'ollama-cloud', model: 'chosen' });
  assert.deepEqual(selectedModel({ id: 'jaeger-gateway' }, vscode),
    { provider: 'openai', model: 'configured' });
});

test('registers live Gateway models only after authorization succeeds', async () => {
  let vendor = '';
  const subscriptions = [];
  const registration = { dispose() {} };
  const vscode = {
    lm: { registerLanguageModelChatProvider(id, provider) { vendor = id; return registration; } },
    workspace: { getConfiguration: () => ({ get: () => '' }), workspaceFolders: [] },
  };
  const catalog = { providers: [
    { id: 'ollama-cloud', display_name: 'Ollama Cloud', reachable: true,
      models: [{ id: 'glm-5.3-flash:cloud', available: true }] },
  ] };
  const gateway = { models: async () => catalog };
  const provider = registerJaegerLanguageModelProvider(vscode, { subscriptions }, gateway);

  assert.equal(vendor, 'jaeger');
  assert.deepEqual(subscriptions, [registration]);
  assert.deepEqual((await provider.provideLanguageModelChatInformation()).map(model => model.id),
    ['ollama-cloud::glm-5.3-flash:cloud']);
});

test('empty authorized catalog retains a Gateway default fallback', async () => {
  let provider;
  const vscode = {
    lm: { registerLanguageModelChatProvider(_id, value) { provider = value; return { dispose() {} }; } },
    workspace: { getConfiguration: () => ({ get: () => '' }), workspaceFolders: [] },
  };
  registerJaegerLanguageModelProvider(vscode, { subscriptions: [] }, { models: async () => ({ providers: [] }) });
  assert.deepEqual(await provider.provideLanguageModelChatInformation(), [modelInformation()]);
});

test('provider sends the model selected by the native VS Code picker', async () => {
  let provider;
  let sent;
  const vscode = {
    LanguageModelChatMessageRole: { User: 1 },
    LanguageModelTextPart: class { constructor(value) { this.value = value; } },
    lm: { registerLanguageModelChatProvider(_id, value) { provider = value; return { dispose() {} }; } },
    workspace: { getConfiguration: () => ({ get: () => 'openai::configured' }), workspaceFolders: [] },
  };
  const gateway = {
    models: async () => ({ providers: [] }),
    create: async body => ({ session_id: body.session_id }),
    send: async (_sessionId, body) => { sent = body; return { status: 'completed', start_event_id: 1 }; },
    receipt: async () => ({ status: 'completed', result: { output: 'done' } }),
  };
  registerJaegerLanguageModelProvider(vscode, { subscriptions: [] }, gateway);
  const reported = [];
  await provider.provideLanguageModelChatResponse(
    { id: 'ollama-cloud::chosen-model' },
    [{ role: 1, content: [{ value: 'Use the picker' }] }],
    {},
    { report: part => reported.push(part.value) },
    { onCancellationRequested: () => ({ dispose() {} }) },
  );
  assert.equal(sent.provider, 'ollama-cloud');
  assert.equal(sent.model, 'chosen-model');
  assert.deepEqual(reported, ['done']);
});

test('provider keeps an active CLI picker choice under Gateway routing authority', async () => {
  let provider;
  let sent;
  const vscode = {
    LanguageModelChatMessageRole: { User: 1 },
    LanguageModelTextPart: class { constructor(value) { this.value = value; } },
    lm: { registerLanguageModelChatProvider(_id, value) { provider = value; return { dispose() {} }; } },
    workspace: { getConfiguration: () => ({ get: () => 'openai::configured' }), workspaceFolders: [] },
  };
  const gateway = {
    create: async body => ({ session_id: body.session_id }),
    send: async (_sessionId, body) => { sent = body; return { status: 'completed', start_event_id: 1 }; },
    receipt: async () => ({ status: 'completed', result: { output: 'done' } }),
  };
  registerJaegerLanguageModelProvider(vscode, { subscriptions: [] }, gateway);
  await provider.provideLanguageModelChatResponse(
    { id: 'cli::grok' },
    [{ role: 1, content: [{ value: 'Use the active CLI runtime' }] }],
    {},
    { report() {} },
    { onCancellationRequested: () => ({ dispose() {} }) },
  );
  assert.equal('provider' in sent, false);
  assert.equal('model' in sent, false);
});
