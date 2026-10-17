/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

const here = (path: string) => fileURLToPath(new URL(path, import.meta.url));

// Dev proxy: the browser only ever talks to its own origin. /v1 and /api go to
// the Jaeger WebUI (127.0.0.1:8790), which already proxies the gateway and
// adds the caller token on the server side. This config never reads a token.
// Point it elsewhere with JAEGER_WEBUI_URL (loopback only), e.g. the test
// stack: JAEGER_WEBUI_URL=http://127.0.0.1:18790 npm run dev
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = (env.JAEGER_WEBUI_URL || "http://127.0.0.1:8790").replace(/\/+$/, "");
  if (!/^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(target)) {
    throw new Error(`JAEGER_WEBUI_URL must be a loopback http origin, got ${target}`);
  }
  const proxy = { "/v1": { target, changeOrigin: false }, "/api": { target, changeOrigin: false } };
  return {
    base: "./",
    plugins: [react()],
    resolve: {
      alias: [
        { find: /^@aether\/ui\/tokens\.css$/, replacement: here("./vendor/aether-ui/tokens/tokens.css") },
        { find: /^@aether\/ui\/home\.css$/, replacement: here("./vendor/aether-ui/tokens/home.css") },
        { find: /^@aether\/ui\/widgets\.css$/, replacement: here("./vendor/aether-ui/src/widgets.css") },
        { find: /^@aether\/ui$/, replacement: here("./vendor/aether-ui/src/index.ts") },
      ],
    },
    server: { host: "127.0.0.1", strictPort: true, proxy },
    preview: { host: "127.0.0.1", strictPort: true, proxy },
    build: { outDir: "dist", emptyOutDir: true },
    test: { environment: "jsdom", include: ["src/**/*.test.ts", "src/**/*.test.tsx"] },
  };
});
