/**
 * Vitest Configuration for Jaeger UI
 *
 * Tests React components with jsdom environment.
 * Supports TypeScript, JSX, and CSS modules.
 */

import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'
import os from 'node:os'
import { fileURLToPath } from 'node:url'

const here = (p: string) => fileURLToPath(new URL(p, import.meta.url));

export default defineConfig({
  cacheDir: path.join(os.tmpdir(), `jaeger-vitest-cache-${process.pid}`),
  plugins: [react()],
  test: {
    // Environment
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],

    // Coverage
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html', 'lcov'],
      reportsDirectory: './coverage',
      exclude: [
        'node_modules/',
        'src/test/',
        '**/*.d.ts',
        '**/*.config.*',
        '**/dist/',
      ],
      thresholds: {
        lines: 60,
        functions: 60,
        branches: 50,
        statements: 60,
      },
    },

    // Test patterns
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    exclude: ['node_modules/', 'dist/', 'tests/e2e/'],

    // Timeouts
    testTimeout: 10000,
    hookTimeout: 10000,

    // Reporters
    reporters: ['verbose', 'json'],
    outputFile: {
      json: process.env.JAEGER_TEST_RESULTS || path.join(os.tmpdir(), `jaeger-vitest-${process.pid}.json`),
    },
  },

  resolve: {
    alias: [
      // Mirror vite.config.ts so tests resolve the vendored Aether UI the
      // same way the app build does.
      { find: /^@aether\/ui\/tokens\.css$/, replacement: here('./vendor/aether-ui/tokens/tokens.css') },
      { find: /^@aether\/ui\/home\.css$/, replacement: here('./vendor/aether-ui/tokens/home.css') },
      { find: /^@aether\/ui\/widgets\.css$/, replacement: here('./vendor/aether-ui/src/widgets.css') },
      { find: /^@aether\/ui$/, replacement: here('./vendor/aether-ui/src/index.ts') },
      { find: /^@jaeger\/ui-protocol$/, replacement: here('../../../packages/jaeger-ui-protocol/src/index.ts') },
      { find: /^@jaeger\/ui-sdk$/, replacement: here('../../../packages/jaeger-ui-sdk/src/index.ts') },
      { find: /^@jaeger\/ui-kit$/, replacement: here('../../../packages/jaeger-ui-kit/src/index.ts') },
      { find: /^@jaeger\/ui-features$/, replacement: here('../../../packages/jaeger-ui-features/src/index.ts') },
      { find: /^react\/jsx-runtime$/, replacement: here('./node_modules/react/jsx-runtime.js') },
      { find: /^react\/jsx-dev-runtime$/, replacement: here('./node_modules/react/jsx-dev-runtime.js') },
      { find: /^react$/, replacement: here('./node_modules/react/index.js') },
      { find: /^react-dom$/, replacement: here('./node_modules/react-dom/index.js') },
      { find: '@', replacement: here('./src') },
    ],
    dedupe: ['react', 'react-dom'],
  },
})
