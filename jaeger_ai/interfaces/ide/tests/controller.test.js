/**
 * Tests for JaegerController
 *
 * Run with: node --test tests/controller.test.js
 *
 * Note: These are unit tests that mock VS Code and Gateway.
 * Integration testing requires VS Code Extension Development Host (F5).
 */

'use strict';

const { test, describe, beforeEach, afterEach, mock } = require('node:test');
const assert = require('node:assert');

// ─────────────────────────────────────────────────────────────
// Mocks
// ─────────────────────────────────────────────────────────────

// Mock VS Code API
const vscodeMock = {
  window: {
    createStatusBarItem: mock.fn(() => ({
      show: mock.fn(),
      dispose: mock.fn(),
      text: '',
      tooltip: '',
      command: '',
    })),
    createOutputChannel: mock.fn(() => ({
      appendLine: mock.fn(),
      dispose: mock.fn(),
    })),
    showInputBox: mock.fn(),
    showInformationMessage: mock.fn(),
    showWarningMessage: mock.fn(),
    showErrorMessage: mock.fn(),
    showQuickPick: mock.fn(),
    activeTextEditor: null,
    onDidChangeActiveTextEditor: mock.fn(),
  },
  workspace: {
    getConfiguration: mock.fn(() => ({
      get: mock.fn(),
      update: mock.fn(),
    })),
    workspaceFolders: [],
    getWorkspaceFolder: mock.fn(),
    onDidChangeTextDocument: mock.fn(),
  },
  commands: {
    registerCommand: mock.fn(),
    executeCommand: mock.fn(),
  },
  languages: {
    registerCodeActionsProvider: mock.fn(),
    registerInlineCompletionItemProvider: mock.fn(),
    getDiagnostics: mock.fn(() => []),
  },
  window: {
    registerWebviewViewProvider: mock.fn(),
    createStatusBarItem: mock.fn(() => ({
      show: mock.fn(),
      dispose: mock.fn(),
      text: '',
      tooltip: '',
      command: '',
    })),
  },
  chat: {
    createChatParticipant: mock.fn(() => ({
      iconPath: null,
      dispose: mock.fn(),
    })),
  },
  StatusBarAlignment: { Left: 1, Right: 2 },
  ViewColumn: { Active: 1, Beside: 2, One: 1, Two: 2, Three: 3 },
  CodeAction: class CodeAction {
    constructor(title, kind) {
      this.title = title;
      this.kind = kind;
    }
  },
  CodeActionKind: {
    QuickFix: { value: 'quickfix' },
    Refactor: { value: 'refactor' },
    RefactorRewrite: { value: 'refactor.rewrite' },
    RefactorExtract: { value: 'refactor.extract' },
  },
  InlineCompletionItem: class InlineCompletionItem {
    constructor(insertText, range) {
      this.insertText = insertText;
      this.range = range;
    }
  },
  SnippetString: class SnippetString {
    constructor(value) { this.value = value; }
  },
  Range: class Range {
    constructor(start, end) { this.start = start; this.end = end; }
  },
  Position: class Position {
    constructor(line, character) { this.line = line; this.character = character; }
  },
  Selection: class Selection {
    constructor(anchor, active) {
      this.anchor = anchor;
      this.active = active;
      this.start = anchor;
      this.end = active;
      this.isEmpty = anchor === active;
    }
  },
  Uri: {
    parse: mock.fn((s) => ({ toString: () => s })),
    file: mock.fn((s) => ({ fsPath: s, scheme: 'file' })),
    joinPath: mock.fn(),
  },
  ThemeColor: class ThemeColor {
    constructor(id) { this.id = id; }
  },
  Disposable: class Disposable {
    constructor(fn) { this.fn = fn; }
    dispose() { this.fn?.(); }
  },
  env: {
    openExternal: mock.fn(),
  },
};

// Mock Gateway
const createMockGateway = () => ({
  json: mock.fn(async (path) => {
    if (path === '/health') {
      return {
        status: 'ok',
        service: 'jaeger-gateway',
        version: '0.13.0',
        model: 'gemma4:12b',
        diagnostics: {
          owner_runtime: { resident: true, execution_verified: true },
        },
      };
    }
    if (path === '/v1/sessions') {
      return { id: 'session-123', title: 'Test' };
    }
    throw new Error(`Unexpected path: ${path}`);
  }),
  create: mock.fn(async (body) => ({ id: 'session-123', ...body })),
  send: mock.fn(async (id, body) => ({ request_id: 'req-123', ...body })),
  models: mock.fn(async () => ({ models: [] })),
  url: 'http://127.0.0.1:33418',
});

// ─────────────────────────────────────────────────────────────
// Test Helpers
// ─────────────────────────────────────────────────────────────

function createMockContext() {
  return {
    subscriptions: [],
    secrets: {
      store: mock.fn(),
      get: mock.fn(),
      delete: mock.fn(),
    },
    extensionUri: { fsPath: '/mock/extension' },
  };
}

function createMockEditor(code = '', language = 'typescript', filePath = '/test/file.ts') {
  const lines = code.split('\n');
  return {
    document: {
      uri: { fsPath: filePath, scheme: 'file' },
      languageId: language,
      lineCount: lines.length,
      lineAt: (line) => ({
        text: lines[line] || '',
        lineNumber: line,
      }),
      getText: (range) => {
        if (!range) return code;
        // Simple mock — returns full code
        return code;
      },
    },
    selection: {
      isEmpty: false,
      start: { line: 0, character: 0 },
      end: { line: lines.length - 1, character: 0 },
      active: { line: 0, character: 0 },
    },
  };
}

// ─────────────────────────────────────────────────────────────
// Module Loading
// ─────────────────────────────────────────────────────────────

// Mock the 'vscode' module using Module._load override
const Module = require('module');
const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') {
    return vscodeMock;
  }
  return originalLoad.apply(this, arguments);
};

// Load controller after mocks
const { JaegerController, JaegerCodeActionProvider } = require('../controller');

// Restore original load
Module._load = originalLoad;

// ─────────────────────────────────────────────────────────────
// Tests
// ─────────────────────────────────────────────────────────────

describe('JaegerController', () => {
  let controller;
  let mockGateway;
  let mockContext;

  beforeEach(() => {
    mockGateway = createMockGateway();
    mockContext = createMockContext();
    controller = new JaegerController(mockContext, mockGateway);
    // Don't call activate() to avoid status bar/polling
  });

  afterEach(() => {
    controller?.dispose();
  });

  describe('state management', () => {
    test('initial state is idle', () => {
      const state = controller.state;
      assert.strictEqual(state.status, 'idle');
    });

    test('state updates trigger listeners', () => {
      const listener = mock.fn();
      controller.onStateChange(listener);
      controller._setState({ status: 'thinking' });
      assert.strictEqual(listener.mock.callCount(), 1);
      assert.strictEqual(listener.mock.calls[0].arguments[0].status, 'thinking');
    });

    test('state is immutable (returns copy)', () => {
      const state1 = controller.state;
      controller._setState({ status: 'working' });
      const state2 = controller.state;
      assert.notStrictEqual(state1, state2);
      assert.strictEqual(state1.status, 'idle');
      assert.strictEqual(state2.status, 'working');
    });
  });

  describe('getCodeContext', () => {
    test('returns null when no editor is active', () => {
      vscodeMock.window.activeTextEditor = null;
      const ctx = controller.getCodeContext();
      assert.strictEqual(ctx, null);
    });

    test('returns code context for active editor', () => {
      vscodeMock.window.activeTextEditor = createMockEditor(
        'const x = 1;\nconst y = 2;',
        'typescript',
        '/workspace/test.ts'
      );
      vscodeMock.workspace.workspaceFolders = [{ uri: { fsPath: '/workspace' }, name: 'workspace' }];
      vscodeMock.workspace.getWorkspaceFolder = () => ({ uri: { fsPath: '/workspace' }, name: 'workspace' });

      const ctx = controller.getCodeContext();
      assert.ok(ctx);
      assert.strictEqual(ctx.language, 'typescript');
      assert.ok(ctx.code.includes('const x = 1;'));
    });
  });

  describe('getWorkspaceContext', () => {
    test('returns workspace info', () => {
      vscodeMock.workspace.workspaceFolders = [
        { uri: { fsPath: '/project' }, name: 'my-project' },
      ];
      const ctx = controller.getWorkspaceContext();
      assert.strictEqual(ctx.name, 'my-project');
      assert.deepStrictEqual(ctx.folders, ['/project']);
    });

    test('returns fallback when no workspace', () => {
      vscodeMock.workspace.workspaceFolders = [];
      const ctx = controller.getWorkspaceContext();
      assert.strictEqual(ctx.name, 'No workspace');
    });
  });

  describe('ask', () => {
    test('sends message to gateway and opens chat', async () => {
      vscodeMock.commands.executeCommand = mock.fn();
      vscodeMock.env.openExternal = mock.fn();

      await controller.ask('Test message');

      assert.strictEqual(mockGateway.create.mock.callCount(), 1);
      assert.strictEqual(mockGateway.send.mock.callCount(), 1);
    });

    test('includes code context when requested', async () => {
      vscodeMock.window.activeTextEditor = createMockEditor('const x = 1;', 'typescript');
      vscodeMock.workspace.workspaceFolders = [{ uri: { fsPath: '/test' }, name: 'test' }];
      vscodeMock.workspace.getWorkspaceFolder = () => ({ uri: { fsPath: '/test' }, name: 'test' });
      vscodeMock.commands.executeCommand = mock.fn();
      vscodeMock.env.openExternal = mock.fn();

      await controller.ask('Explain this', { includeCode: true });

      const sendCall = mockGateway.send.mock.calls[0];
      const payload = sendCall.arguments[1];
      assert.ok(payload.context.code);
      assert.ok(payload.context.code.code.includes('const x = 1;'));
    });

    test('handles gateway errors', async () => {
      mockGateway.create = mock.fn(async () => { throw new Error('Gateway down'); });
      await assert.rejects(() => controller.ask('Test'), /Gateway down/);
    });
  });

  describe('quick actions', () => {
    beforeEach(() => {
      vscodeMock.window.activeTextEditor = createMockEditor(
        'function add(a, b) {\n  return a + b;\n}',
        'typescript',
        '/test/math.ts'
      );
      vscodeMock.workspace.workspaceFolders = [{ uri: { fsPath: '/test' }, name: 'test' }];
      vscodeMock.workspace.getWorkspaceFolder = () => ({ uri: { fsPath: '/test' }, name: 'test' });
      vscodeMock.commands.executeCommand = mock.fn();
      vscodeMock.env.openExternal = mock.fn();
    });

    test('explainCode sends explain prompt', async () => {
      await controller.explainCode();
      const sendCall = mockGateway.send.mock.calls[0];
      const payload = sendCall.arguments[1];
      assert.ok(payload.text.includes('Explain'));
    });

    test('fixCode sends fix prompt', async () => {
      await controller.fixCode();
      const sendCall = mockGateway.send.mock.calls[0];
      const payload = sendCall.arguments[1];
      assert.ok(payload.text.includes('Fix'));
    });

    test('writeTests sends test prompt', async () => {
      await controller.writeTests();
      const sendCall = mockGateway.send.mock.calls[0];
      const payload = sendCall.arguments[1];
      assert.ok(payload.text.includes('tests'));
    });

    test('refactorCode sends refactor prompt', async () => {
      await controller.refactorCode();
      const sendCall = mockGateway.send.mock.calls[0];
      const payload = sendCall.arguments[1];
      assert.ok(payload.text.toLowerCase().includes('refactor'));
    });

    test('documentCode sends documentation prompt', async () => {
      await controller.documentCode();
      const sendCall = mockGateway.send.mock.calls[0];
      const payload = sendCall.arguments[1];
      assert.ok(payload.text.toLowerCase().includes('documentation') || payload.text.toLowerCase().includes('comments'));
    });

    test('reviewCode sends review prompt', async () => {
      await controller.reviewCode();
      const sendCall = mockGateway.send.mock.calls[0];
      const payload = sendCall.arguments[1];
      assert.ok(payload.text.toLowerCase().includes('review'));
    });
  });

  describe('openChat', () => {
    test('tries Simple Browser first', async () => {
      vscodeMock.commands.executeCommand = mock.fn(async () => {});
      await controller.openChat();
      assert.ok(vscodeMock.commands.executeCommand.mock.calls.length > 0);
    });

    test('falls back to external browser', async () => {
      vscodeMock.commands.executeCommand = mock.fn(async () => { throw new Error('Simple Browser not available'); });
      vscodeMock.env.openExternal = mock.fn();
      await controller.openChat();
      assert.ok(vscodeMock.env.openExternal.mock.calls.length > 0);
    });
  });
});

describe('JaegerCodeActionProvider', () => {
  let provider;
  let controller;

  beforeEach(() => {
    controller = new JaegerController(createMockContext(), createMockGateway());
    provider = new JaegerCodeActionProvider(controller);
  });

  test('provides code actions for file scheme', () => {
    const document = { uri: { scheme: 'file' } };
    const range = {};
    const context = {};
    const token = {};

    const actions = provider.provideCodeActions(document, range, context, token);
    assert.ok(Array.isArray(actions));
    assert.ok(actions.length >= 5); // Explain, Fix, Test, Refactor, Document, Review
  });

  test('returns empty for non-file scheme', () => {
    const document = { uri: { scheme: 'untitled' } };
    const actions = provider.provideCodeActions(document, {}, {}, {});
    assert.deepStrictEqual(actions, []);
  });

  test('actions have correct commands', () => {
    const document = { uri: { scheme: 'file' } };
    const actions = provider.provideCodeActions(document, {}, {}, {});
    const commands = actions.map(a => a.command?.command);

    assert.ok(commands.includes('jaeger.explainCode'));
    assert.ok(commands.includes('jaeger.fixCode'));
    assert.ok(commands.includes('jaeger.writeTests'));
    assert.ok(commands.includes('jaeger.refactorCode'));
    assert.ok(commands.includes('jaeger.documentCode'));
    assert.ok(commands.includes('jaeger.reviewCode'));
  });
});

// ─────────────────────────────────────────────────────────────
// Integration Tests (require VS Code Extension Host)
// ─────────────────────────────────────────────────────────────

describe('Integration (requires Extension Host)', () => {
  test.skip('status bar shows agent state', () => {
    // This test runs in VS Code Extension Development Host (F5)
    // Manual verification: Check status bar shows "Jaeger" text
  });

  test.skip('right-click menu shows Ask Jaeger actions', () => {
    // Manual verification: Select code, right-click, see "Ask Jaeger" submenu
  });

  test.skip('@jaeger chat participant responds', () => {
    // Manual verification: Type @jaeger status in VS Code Chat
  });

  test.skip('Cmd+Shift+J opens chat', () => {
    // Manual verification: Press Cmd+Shift+J, chat opens
  });
});
