import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";

const here = (p: string) => fileURLToPath(new URL(p, import.meta.url));

export default defineConfig({
  cacheDir: path.join(os.tmpdir(), `jaeger-vitest-cache-${process.pid}`),
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    exclude: ["node_modules/", "dist/"],
    testTimeout: 10000,
  },
  resolve: {
    alias: [
      { find: /^lucide-react$/, replacement: here("./node_modules/lucide-react/dist/esm/lucide-react.mjs") },
      { find: /^@jaeger\/ui-kit\/tokens\.css$/, replacement: here("../../../packages/jaeger-ui-kit/src/tokens.css") },
      { find: /^@jaeger\/ui-protocol$/, replacement: here("../../../packages/jaeger-ui-protocol/src/index.ts") },
      { find: /^@jaeger\/ui-sdk$/, replacement: here("../../../packages/jaeger-ui-sdk/src/index.ts") },
      { find: /^@jaeger\/ui-kit$/, replacement: here("../../../packages/jaeger-ui-kit/src/index.ts") },
      { find: /^@jaeger\/ui-avatar$/, replacement: here("../../../packages/jaeger-ui-avatar/src/index.ts") },
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
});
