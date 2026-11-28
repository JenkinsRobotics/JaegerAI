/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

const here = (path: string) => fileURLToPath(new URL(path, import.meta.url));

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = (env.JAEGER_WEBUI_URL || "http://127.0.0.1:8790").replace(/\/+$/, "");
  const proxy = { "/v1": { target, changeOrigin: false, ws: true }, "/health": { target, changeOrigin: false } };
  return {
    base: "/",
    plugins: [react()],
    resolve: {
      alias: [
        { find: "lucide-react", replacement: here("./node_modules/lucide-react/dist/esm/lucide-react.mjs") },
        { find: /^@jaeger\/ui-kit\/tokens\.css$/, replacement: here("../../../packages/jaeger-ui-kit/src/tokens.css") },
        { find: /^@jaeger\/ui-protocol$/, replacement: here("../../../packages/jaeger-ui-protocol/src/index.ts") },
        { find: /^@jaeger\/ui-sdk$/, replacement: here("../../../packages/jaeger-ui-sdk/src/index.ts") },
        { find: /^@jaeger\/ui-kit$/, replacement: here("../../../packages/jaeger-ui-kit/src/index.ts") },
        { find: /^@jaeger\/ui-avatar$/, replacement: here("../../../packages/jaeger-ui-avatar/src/index.ts") },
        { find: /^@jaeger\/ui-office$/, replacement: here("../../../packages/jaeger-ui-office/src/index.ts") },
        { find: /^@jaeger\/ui-features$/, replacement: here("../../../packages/jaeger-ui-features/src/index.ts") },
        { find: /^react\/jsx-runtime$/, replacement: here("./node_modules/react/jsx-runtime.js") },
        { find: /^react\/jsx-dev-runtime$/, replacement: here("./node_modules/react/jsx-dev-runtime.js") },
        { find: /^react$/, replacement: here("./node_modules/react/index.js") },
        { find: /^react-dom$/, replacement: here("./node_modules/react-dom/index.js") },
        { find: /^three$/, replacement: here("./node_modules/three/build/three.module.js") },
        { find: /^three\/(.*)$/, replacement: `${here("./node_modules/three")}/$1` },
        { find: /^@pixiv\/three-vrm$/, replacement: here("./node_modules/@pixiv/three-vrm/lib/three-vrm.module.js") },
      ],
      dedupe: ["react", "react-dom"],
    },
    server: { host: "127.0.0.1", strictPort: true, proxy, fs: { allow: [here("."), here("../../../packages")] } },
    preview: { host: "127.0.0.1", strictPort: true, proxy },
    build: { outDir: "dist", emptyOutDir: true },
  };
});
