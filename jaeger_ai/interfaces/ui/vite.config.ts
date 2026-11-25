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
  const proxy = { "/v1": { target, changeOrigin: false, ws: true }, "/api": { target, changeOrigin: false } };
  return {
    base: "/",
    plugins: [react()],
    resolve: {
      alias: [
        { find: /^@aether\/ui\/tokens\.css$/, replacement: here("./vendor/aether-ui/tokens/tokens.css") },
        { find: /^@aether\/ui\/home\.css$/, replacement: here("./vendor/aether-ui/tokens/home.css") },
        { find: /^@aether\/ui\/widgets\.css$/, replacement: here("./vendor/aether-ui/src/widgets.css") },
        { find: /^@aether\/ui$/, replacement: here("./vendor/aether-ui/src/index.ts") },
        { find: /^@jaeger\/ui-protocol$/, replacement: here("../../../packages/jaeger-ui-protocol/src/index.ts") },
        { find: /^@jaeger\/ui-sdk$/, replacement: here("../../../packages/jaeger-ui-sdk/src/index.ts") },
        { find: /^@jaeger\/ui-kit$/, replacement: here("../../../packages/jaeger-ui-kit/src/index.ts") },
        { find: /^@jaeger\/ui-features$/, replacement: here("../../../packages/jaeger-ui-features/src/index.ts") },
        { find: /^react\/jsx-runtime$/, replacement: here("./node_modules/react/jsx-runtime.js") },
        { find: /^react\/jsx-dev-runtime$/, replacement: here("./node_modules/react/jsx-dev-runtime.js") },
        { find: /^react$/, replacement: here("./node_modules/react/index.js") },
        { find: /^react-dom$/, replacement: here("./node_modules/react-dom/index.js") },
      ],
      dedupe: ["react", "react-dom"],
    },
    server: { host: "127.0.0.1", strictPort: true, proxy, fs: { allow: [here("."), here("../ide/media"), here("../../../packages")] } },
    preview: { host: "127.0.0.1", strictPort: true, proxy },
    build: { outDir: "dist", emptyOutDir: true },
    test: { environment: "jsdom", include: ["src/**/*.test.ts", "src/**/*.test.tsx"] },
  };
});
