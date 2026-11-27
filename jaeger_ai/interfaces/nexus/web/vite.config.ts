import { defineConfig } from 'vite';
// The built screen goes outside the repo (Jaeger AI's Golden Rule 1); serve.py serves it from there.
// `python -m jaeger_ai.interfaces.nexus --build` runs this with the same outDir.
import { homedir } from 'node:os';
export default defineConfig({ base: './', esbuild: { jsx: 'automatic' }, build: { outDir: `${homedir()}/.cache/jaeger/nexus-ui/dist`, emptyOutDir: true } });
