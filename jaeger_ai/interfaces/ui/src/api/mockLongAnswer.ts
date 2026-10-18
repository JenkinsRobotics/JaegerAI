// Dev mock only: a long, realistic reply for Scripts/live-prompt.txt (two read-only tools, then markdown with
// headings, a list, a table and a code fence) streamed in LLM-sized bursts, so the stream style can be seen
// and recorded without a model. Content is illustrative, not from a real run.
import type { GatewayEvent } from "./types";

export const LONG_ANSWER = `## Overview

Jaeger is a local-first agent runtime: one **gateway** process owns sessions, tools and approvals, and every
interface (the Mac app, the WebUI, the IDE chat) is a thin client over its HTTP + SSE API. The README calls it
"one brain, many windows", and that is a fair summary of \`jaeger_ai/core/gateway/server.py\`.

## How it's organised

- **Gateway** (\`core/gateway/\`): sessions, turns, the event log and the approval queue.
- **Agent registry** (\`core/agent_registry/\`): the lead agent plus role specialists and their skills.
- **Interfaces** (\`interfaces/\`): the Mac shell, the React main screen and the IDE bridge.
- **Features** (\`features/\`): optional add-ons such as the WebUI adapter and roundtable debates.

| Component | What it does | Key file |
| --- | --- | --- |
| Gateway | Owns sessions, streams events, gates tools | \`core/gateway/server.py\` |
| Session store | SQLite transcript, pages and summaries | \`core/gateway/session_store.py\` |
| Main screen | The chat UI every host embeds | \`interfaces/ui/src/App.tsx\` |

## Getting started

Clone the repo, create the venv and start an isolated gateway on a loopback port. The README's quick start
boils down to:

\`\`\`bash
python3 -m venv ~/.jaeger/venv && ~/.jaeger/venv/bin/pip install -e .
JAEGER_STATE_DIR=~/.cache/jaeger/dev python -m jaeger_ai.core.gateway.server --host 127.0.0.1 --port 43438
\`\`\`

Then open the main screen against it; the dev token proxy adds the caller token, so nothing secret lives in
the page.

## Risks and open questions

The session contract only just landed, so clients still carry a fallback for older gateways. Uploaded files
don't reappear in reloaded user messages yet, and the rolling summary (after 24 unsummarised messages) is
new enough that long chats deserve a manual look before you rely on it.`;

/** Two read-only tools, a short think, then the answer in 6–28 character bursts every ~45 ms. */
export function longAnswerScript(sessionId: string): Array<[number, GatewayEvent]> {
  const out: Array<[number, GatewayEvent]> = [
    [150, { event: "turn.start", session_id: sessionId }],
    [300, { event: "turn.reasoning", payload: { text: "Find the README and a main source file, read both.", duration_ms: 2_000 } }],
    [250, { event: "tool.started", payload: { call_id: "m1", tool: "search_files", input: { pattern: "README*" } } }],
    [700, { event: "tool.completed", payload: { call_id: "m1", tool: "search_files", output: "README.md" } }],
    [200, { event: "tool.started", payload: { call_id: "m2", tool: "read_file", input: { path: "README.md" } } }],
    [800, { event: "tool.completed", payload: { call_id: "m2", tool: "read_file", output: "584 lines" } }],
  ];
  let seed = 7;
  const rand = () => (seed = (seed * 9301 + 49297) % 233280) / 233280;
  for (let i = 0; i < LONG_ANSWER.length;) {
    const n = 6 + Math.floor(rand() * 22);
    out.push([30 + Math.floor(rand() * 30), { event: "turn.delta", payload: { delta: LONG_ANSWER.slice(i, i + n), channel: "provisional" } }]);
    i += n;
  }
  out.push([200, { event: "turn.finish", payload: {} }]);
  return out;
}
