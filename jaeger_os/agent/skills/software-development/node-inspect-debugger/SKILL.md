---
name: node-inspect-debugger
description: "Debug Node.js with real breakpoints via --inspect + the V8 inspector (node inspect CLI or scripted Chrome DevTools Protocol). Load this when console.log isn't enough: a Node/tsx test fails, an Ink/React TUI misbehaves, or you need to inspect a closure value, call stack, CPU profile, or heap snapshot."
version: 2.0.0
platforms: [macos, linux, windows]
requires_tools: [terminal, start_background, check_background, stop_background, read_file, search_files, write_file]
metadata:
  jros:
    tags: [debugging, nodejs, node-inspect, cdp, breakpoints, profiling]
    category: software-development
    related_skills: [systematic-debugging, test-driven-development]
---

# NODE.JS INSPECT DEBUGGER

Drive Node's built-in V8 inspector to get breakpoints, step in/over/out, call-stack walking,
scope dumps, and expression evaluation in a paused frame. Two paths:

- `node inspect` — zero-install interactive CLI REPL. Best for a human at a prompt.
- SCRIPTED CDP via `chrome-remote-interface` — best FOR AN AGENT: it is non-interactive,
  scriptable, and repeatable. Prefer this path when driving from JROS tools, because the
  interactive REPL is hard to steer through a one-shot `terminal` call.

## WHEN TO USE
A Node/tsx test fails and you need intermediate state · an Ink/React TUI crashes or renders
wrong · a value lives in a closure `console.log` can't reach · you need a CPU profile or heap
snapshot from a running process. DON'T use it for anything `console.log` solves in a minute —
breakpoint debugging is heavier; spend it where the payoff is real.

## TOOLS (JROS)
- `terminal(command=…)` — run `node`, `npm`, `curl`, `node inspect`, and the CDP driver.
- `start_background(...)` / `check_background(id=…)` / `stop_background(id=…)` — keep a long-lived
  target (dev server, `--inspect` process) alive across turns and read its output, instead of
  blocking on an interactive REPL.
- `write_file(path="skills/cdp-debug.js", text=…)` — save the CDP driver script.
- `read_file` / `search_files` — locate the source line to break on.

## FLAGS THAT MATTER
- `node --inspect script.js` — inspector on `127.0.0.1:9229`, does NOT pause.
- `node --inspect-brk script.js` — inspector on AND pause on the first line. Use this whenever
  you must set breakpoints before any code runs.
- `node --inspect=0.0.0.0:9230` — custom host:port. NEVER bind `0.0.0.0` off an isolated
  network: it exposes arbitrary code execution. Default `127.0.0.1` is correct.
- TypeScript via tsx: `node --inspect-brk --import tsx script.ts`.

## PATH A — `node inspect` REPL (interactive)
Launch: `node inspect path/to/script.js` (or `node --inspect-brk $(which tsx) script.ts`).
At the `debug>` prompt: `c`/`cont` continue · `n` step over · `s` step into · `o` step out ·
`pause` · `sb('file.js', 42)` set breakpoint · `sb('funcName')` break on call · `cb(...)` clear ·
`breakpoints` list · `bt` backtrace · `list(5)` show source · `watch('expr')` · `exec expr`
eval once · `repl` drop into current scope (Ctrl+C exits) · `restart` · `kill` · `.exit`.
Inside `repl` you can read any local/closure variable.

Attach to an ALREADY-RUNNING process:
```bash
kill -SIGUSR1 <pid>                 # Node prints: Debugger listening on ws://127.0.0.1:9229/<uuid>
node inspect -p <pid>               # or: node inspect ws://127.0.0.1:9229/<uuid>
```
Find the URL: `curl -s http://127.0.0.1:9229/json/list | jq -r '.[0].webSocketDebuggerUrl'`.

## PATH B — scripted CDP (preferred for the agent)
Install to a throwaway dir so you don't dirty the project, then run the driver:
```bash
mkdir -p /tmp/cdp-tools && cd /tmp/cdp-tools && npm i chrome-remote-interface
```
Save the driver with `write_file(path="skills/cdp-debug.js", …)`. Driver shape:
```javascript
const CDP = require('chrome-remote-interface');
(async () => {
  const client = await CDP({ port: 9229 });
  const { Debugger, Runtime } = client;
  Debugger.paused(async ({ callFrames, reason }) => {
    const top = callFrames[0];
    console.log(`PAUSED ${reason} @ ${top.url}:${top.location.lineNumber + 1}`);
    for (const scope of top.scopeChain) {
      if (scope.type === 'local' || scope.type === 'closure') {
        const { result } = await Runtime.getProperties({ objectId: scope.object.objectId, ownProperties: true });
        for (const p of result) console.log(`  ${scope.type}.${p.name} =`, p.value?.value ?? p.value?.description);
      }
    }
    await Debugger.resume();
  });
  await Runtime.enable(); await Debugger.enable();
  await Debugger.setBreakpointByUrl({ urlRegex: '.*app\\.tsx$', lineNumber: 119 }); // 0-indexed
  await Runtime.runIfWaitingForDebugger();
})();
```
Run the target under the debugger via background so it outlives the turn, then run the driver:
```bash
node --inspect-brk=9229 target.js       # launch via start_background(...) to keep it alive
NODE_PATH=/tmp/cdp-tools/node_modules node skills/cdp-debug.js   # via terminal(...)
```

## PROFILING (non-interactive, from the CDP driver)
Swap `Debugger` for `Profiler` (CPU) or `HeapProfiler` (heap):
```javascript
await client.Profiler.enable(); await client.Profiler.start();
await new Promise(r => setTimeout(r, 5000));
const { profile } = await client.Profiler.stop();
require('fs').writeFileSync('/tmp/cpu.cpuprofile', JSON.stringify(profile)); // open in DevTools → Performance
```

## RUNNING TESTS UNDER THE DEBUGGER
Force a SINGLE worker so you're not debugging a pool:
`node --inspect-brk ./node_modules/vitest/vitest.mjs run --no-file-parallelism src/foo.test.tsx`
(vitest `--no-file-parallelism`, jest `--runInBand`). Then attach with `node inspect -p <pid>`.

## COMMON PITFALLS
1. TS line numbers: breakpoints hit emitted JS. Break in built `dist/*.js`, or use
   `node --enable-source-maps` + a CDP client that follows sourcemaps (`node inspect` CLI does NOT).
2. `--inspect` vs `--inspect-brk`: plain `--inspect` races past early breakpoints if you attach
   late. Use `--inspect-brk` to pause before any code runs.
3. Port collisions: default `9229`. Use `--inspect=0` for a random port and read the real URL
   from `curl -s http://127.0.0.1:9229/json/list`.
4. Children: `--inspect` on a parent does NOT inspect children. Use `NODE_OPTIONS='--inspect'`
   to propagate; Node auto-increments ports per child.
5. Paused targets stay paused if you Ctrl+C out of `node inspect` — `cont` or `kill` first.

## ERROR HATCH
First breakpoint never hits after two tries? You almost certainly used `--inspect` instead of
`--inspect-brk`, or attached after the code already ran. Restart the target with `--inspect-brk`
via `start_background`, confirm the target with `curl .../json/list`, then attach fresh.

## DONE WHEN
The debugger paused where you expected, you read the value / call stack / profile you came for,
and you `kill`ed or `stop_background`ed the target so no inspector is left listening.
