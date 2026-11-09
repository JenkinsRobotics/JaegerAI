'use strict';

const { randomUUID } = require('node:crypto');
const { observeNativeTurn, renderNativeOutcome } = require('./native-turn');
const { admissionModelOverride, parseProviderModel } = require('./media/presentation');

const MODEL_ID = 'jaeger-gateway';
const DEFAULT_CONTEXT_TOKENS = 200000;
const DEFAULT_OUTPUT_TOKENS = 32768;

function messageText(message) {
  return (message?.content || []).map(part => {
    if (typeof part === 'string') return part;
    return typeof part?.value === 'string' ? part.value : '';
  }).join('');
}

function promptFromMessages(messages, userRole = 1) {
  const rows = (messages || []).map(message => ({
    role: message?.role === userRole ? 'User' : 'Assistant',
    text: messageText(message).trim(),
  })).filter(row => row.text);
  if (!rows.length) return '';
  if (rows.length === 1) return rows[0].text;
  return rows.map(row => `${row.role}:\n${row.text}`).join('\n\n');
}

function configuredModel(vscode) {
  return parseProviderModel(vscode.workspace.getConfiguration('jaeger').get('model') || '');
}

function selectedModel(model, vscode) {
  if (model?.id && model.id !== MODEL_ID) {
    const selected = parseProviderModel(model.id);
    if (selected.model) return selected;
  }
  return configuredModel(vscode);
}

function workspaceRoot(vscode) {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '';
}

function modelInformation() {
  return {
    id: MODEL_ID,
    name: 'Jaeger Gateway',
    family: 'jaeger',
    tooltip: 'Jaeger Gateway — sessions, tools, approvals, and model routing stay with Jaeger.',
    detail: 'Local Gateway',
    version: '1',
    maxInputTokens: DEFAULT_CONTEXT_TOKENS,
    maxOutputTokens: DEFAULT_OUTPUT_TOKENS,
    // The Gateway owns the tool loop and approvals. Advertising tool support
    // keeps the model available in native Agent mode; tool execution itself is
    // still performed and persisted by the Gateway, never by the workbench.
    capabilities: { imageInput: false, toolCalling: true },
    isBYOK: true,
    isDefault: true,
    isUserSelectable: true,
  };
}

function providerLabel(provider, providerId) {
  if (providerId === 'ollama-cloud') return 'Ollama Cloud';
  if (providerId === 'cli') return 'CLI Runtime';
  const value = String(provider?.display_name || provider?.displayName || provider?.name || providerId || '').trim();
  return value || 'Jaeger model';
}

function routedModel(providerId, model) {
  let provider = String(providerId || '').trim();
  let id = String(model?.id || model?.name || '').trim();
  if (id.startsWith('@')) {
    const routed = parseProviderModel(id);
    provider = routed.provider || provider;
    id = routed.model;
  }
  if (provider === 'ollama' && (model?.remote_host === 'cloud' || id.endsWith(':cloud'))) {
    provider = 'ollama-cloud';
  }
  return { provider, model: id };
}

function positiveInteger(...values) {
  for (const value of values) {
    const number = Number(value);
    if (Number.isFinite(number) && number > 0) return Math.floor(number);
  }
  return undefined;
}

function supportsImages(model) {
  const capabilities = Array.isArray(model?.capabilities) ? model.capabilities : [];
  if (capabilities.some(value => /vision|image/i.test(String(value)))) return true;
  const vision = model?.certifications?.VISION ?? model?.certifications?.vision;
  return /pass|true|supported/i.test(String(vision || ''));
}

function catalogModelInformation(catalog) {
  const rows = [];
  const seen = new Set();
  const add = (provider, providerId, model, inheritedContext) => {
    if (!model || model.available === false) return;
    const route = routedModel(providerId, model);
    if (!route.provider || !route.model) return;
    const id = `${route.provider}::${route.model}`;
    if (seen.has(id)) return;
    seen.add(id);
    const contextTokens = positiveInteger(
      model.context_length,
      model.contextLength,
      model.context_window,
      model.max_context_tokens,
      inheritedContext,
      DEFAULT_CONTEXT_TOKENS,
    );
    const outputTokens = positiveInteger(model.max_output_tokens, model.maxOutputTokens)
      || Math.min(DEFAULT_OUTPUT_TOKENS, Math.max(4096, Math.floor(contextTokens / 4)));
    const name = String(model.display_name || model.displayName || model.name || route.model).trim();
    const source = providerLabel(provider, route.provider);
    rows.push({
      id,
      name: name || route.model,
      family: String(model.family || route.model),
      tooltip: `${name || route.model} served by ${source} through the Jaeger Gateway. Sessions, tools, and approvals remain Gateway-owned.`,
      detail: `${source} via Jaeger Gateway`,
      version: String(model.version || '1'),
      maxContextWindowTokens: contextTokens,
      maxInputTokens: contextTokens,
      maxOutputTokens: outputTokens,
      capabilities: { imageInput: supportsImages(model), toolCalling: true },
      isBYOK: true,
      isDefault: false,
      isUserSelectable: true,
    });
  };

  for (const provider of Array.isArray(catalog?.providers) ? catalog.providers : []) {
    if (!provider || provider.reachable === false) continue;
    const providerId = String(provider.id || provider.provider_id || '').trim();
    for (const model of Array.isArray(provider.models) ? provider.models : []) {
      add(provider, providerId, model, provider.context_length);
    }
  }

  const groups = Array.isArray(catalog?.groups)
    ? catalog.groups
    : (Array.isArray(catalog?.webui_catalog?.groups) ? catalog.webui_catalog.groups : []);
  for (const group of groups) {
    if (!group) continue;
    const online = group.status ? group.status === 'online' : group.reachable !== false && group.credentials_available !== false;
    if (!online) continue;
    const providerId = String(group.provider_id || group.provider || group.id || '').trim();
    for (const model of Array.isArray(group.models) ? group.models : []) {
      add(group, providerId, model, group.context_length);
    }
  }

  const inventoryActive = catalog?.active || {};
  const webActive = catalog?.webui_catalog || {};
  const active = {
    provider: inventoryActive.provider || inventoryActive.provider_id || webActive.active_provider,
    model: inventoryActive.model || inventoryActive.model_id || webActive.default_model,
    remote_host: inventoryActive.remote_host,
  };
  const activeRoute = routedModel(active.provider, {
    id: active.model,
    remote_host: active.remote_host,
  });
  // Provider probes can be temporarily empty even while the Gateway is actively
  // serving a CLI or delegated runtime. The authoritative active route must
  // still appear as the real native model instead of regressing to the generic
  // "Jaeger Gateway" fallback.
  if (activeRoute.model && !seen.has(`${activeRoute.provider || 'jaeger'}::${activeRoute.model}`)) {
    add(
      { id: activeRoute.provider || 'jaeger', display_name: providerLabel(null, activeRoute.provider || 'jaeger') },
      activeRoute.provider || 'jaeger',
      { id: activeRoute.model, available: true, remote_host: active.remote_host },
    );
  }
  if (!rows.length) return rows;
  let defaultIndex = rows.findIndex(row => row.id === `${activeRoute.provider}::${activeRoute.model}`);
  if (defaultIndex < 0 && activeRoute.model) {
    const matching = rows.map((row, index) => ({ row, index }))
      .filter(item => parseProviderModel(item.row.id).model === activeRoute.model);
    if (matching.length === 1) defaultIndex = matching[0].index;
  }
  if (defaultIndex < 0) defaultIndex = 0;
  return rows.map((row, index) => ({ ...row, isDefault: index === defaultIndex }));
}

function registerJaegerLanguageModelProvider(vscode, context, gateway, output) {
  if (typeof vscode.lm?.registerLanguageModelChatProvider !== 'function') {
    output?.appendLine('[jaeger] Native language-model provider API is unavailable in this host.');
    return undefined;
  }

  const provider = {
    provideLanguageModelChatInformation: async () => {
      // Do not publish a selectable model for a dead or unauthorized Gateway.
      try {
        const catalog = await gateway.models();
        const models = catalogModelInformation(catalog);
        output?.appendLine(`[jaeger] Gateway model catalog available (${models.length} selectable models).`);
        return models.length ? models : [modelInformation()];
      } catch (error) {
        output?.appendLine(`[jaeger] Gateway model discovery failed: ${error?.message || error}`);
        throw error;
      }
    },

    provideTokenCount: async (_model, value) => {
      const text = typeof value === 'string' ? value : messageText(value);
      return Math.max(1, Math.ceil(text.length / 4));
    },

    provideLanguageModelChatResponse: async (model, messages, _options, progress, token) => {
      const prompt = promptFromMessages(messages, vscode.LanguageModelChatMessageRole?.User || 1);
      if (!prompt) return;

      const workspace = workspaceRoot(vscode);
      const sessionId = randomUUID();
      const requestId = randomUUID();
      const aborter = new AbortController();
      const cancellation = token?.onCancellationRequested?.(() => aborter.abort());
      const stream = {
        markdown(value) {
          if (value) progress.report(new vscode.LanguageModelTextPart(String(value)));
        },
        progress() {},
      };

      try {
        await gateway.create({
          session_id: sessionId,
          title: prompt.replace(/\s+/g, ' ').slice(0, 72),
          workspace,
          ...(workspace ? { workspace_folder: workspace } : {}),
          source: 'ide',
        });
        const selected = admissionModelOverride(selectedModel(model, vscode));
        const admitted = await gateway.send(sessionId, {
          text: prompt,
          request_id: requestId,
          workspace,
          ...(selected.model ? {
            model: selected.model,
            ...(selected.provider ? { provider: selected.provider } : {}),
          } : {}),
        });
        const outcome = await observeNativeTurn({
          gateway,
          sessionId,
          requestId,
          admitted,
          signal: aborter.signal,
          stream,
        });
        renderNativeOutcome(stream, outcome, aborter.signal.aborted);
      } finally {
        cancellation?.dispose();
        aborter.abort();
      }
    },
  };

  const registration = vscode.lm.registerLanguageModelChatProvider('jaeger', provider);
  context.subscriptions.push(registration);
  output?.appendLine('[jaeger] Registered Jaeger Gateway as a native chat model provider.');
  if (typeof vscode.lm.selectChatModels === 'function') {
    void Promise.resolve(vscode.lm.selectChatModels({ vendor: 'jaeger' })).then(models => {
      output?.appendLine(`[jaeger] Native model discovery resolved ${models.length} Jaeger model(s).`);
    }).catch(error => {
      output?.appendLine(`[jaeger] Native model discovery failed: ${error?.message || error}`);
    });
  }
  return provider;
}

module.exports = {
  MODEL_ID,
  catalogModelInformation,
  messageText,
  modelInformation,
  promptFromMessages,
  registerJaegerLanguageModelProvider,
  selectedModel,
};
