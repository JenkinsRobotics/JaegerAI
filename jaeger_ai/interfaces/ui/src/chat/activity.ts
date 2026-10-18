/* What the agent is doing right now, in words (Jenkins Robotics, 2026-10-17, original). Pure helpers for the
 * progress line ("Searching the web…") and the collapsed steps summary ("Ran 3 commands · Read 2 files").
 * Pattern from the Grok Bot desktop transcript; the phrases are Jaeger's own. */
import type { ChatPart, ChatTurn } from "./host";

export type ToolPart = Extract<ChatPart, { kind: "toolInvocation" }>;
export type ToolCategory = "search" | "web" | "shell" | "read" | "edit" | "agent" | "other";

/** Tool name → category. Command lines (a name with spaces, e.g. "npm run build") count as shell. */
export function toolCategory(name: string): ToolCategory {
  const n = name.trim().toLowerCase();
  if (/\s/.test(n)) return "shell";
  if (/(^|_)(web_?search|search_web|internet_search|google|brave|bing)(_|$)/.test(n) || n === "search") return "search";
  if (/(fetch|browse|browser|web_?read|read_url|open_url|http_get|scrape|crawl)/.test(n)) return "web";
  if (/(shell|bash|zsh|terminal|exec|run_command|command|execute_code|run_)/.test(n)) return "shell";
  if (/(write|edit|patch|apply|replace|create_file|delete_file|move_file)/.test(n)) return "edit";
  if (/(read|view|cat|list_dir|ls|grep|glob|search_files|find)/.test(n)) return "read";
  if (/(call_agent|handoff|delegate|ask_agent)/.test(n)) return "agent";
  return "other";
}

const RUNNING: Record<ToolCategory, string> = {
  search: "Searching the web…",
  web: "Reading a page…",
  shell: "Running commands…",
  read: "Reading files…",
  edit: "Editing files…",
  agent: "Checking with another agent…",
  other: "Working on it…",
};

const THINKING = ["Thinking…", "Working it out…", "Putting it together…"] as const;

/** Stable per turn, so the phrase does not flicker between renders. */
export function thinkingPhrase(turnId: string): string {
  let h = 0;
  for (let i = 0; i < turnId.length; i += 1) h = (h * 31 + turnId.charCodeAt(i)) >>> 0;
  return THINKING[h % THINKING.length];
}

const isLive = (p: ToolPart) => p.state === "streaming" || p.state === "executing" || p.state === "waitingForConfirmation";

/** The progress line for a pending turn. */
export function activityPhrase(turn: Pick<ChatTurn, "turnId" | "parts">, agentName?: (id: string) => string | undefined): string {
  const parts = turn.parts;
  if (parts.some((p) => p.kind === "confirmation") || parts.some((p) => p.kind === "toolInvocation" && p.state === "waitingForConfirmation")) {
    return "Waiting for your OK";
  }
  for (let i = parts.length - 1; i >= 0; i -= 1) {
    const p = parts[i];
    if (p.kind === "toolInvocation" && isLive(p)) return RUNNING[toolCategory(p.toolName)];
    if (p.kind === "handoff" && p.direction === "to") {
      // Still out with that agent unless it already came back.
      const back = parts.slice(i + 1).some((q) => q.kind === "handoff" && q.direction === "from" && q.handoffId === p.handoffId);
      if (!back) return `Checking with ${agentName?.(p.agentId) ?? p.agentName}…`;
    }
    if (p.kind === "progress" && p.message) return p.message.endsWith("…") ? p.message : `${p.message}…`;
    if (p.kind === "markdownContent" && p.text) break;
  }
  return thinkingPhrase(turn.turnId);
}

const DONE: Record<ToolCategory, (n: number) => string> = {
  search: (n) => (n === 1 ? "Searched the web" : `Searched the web ${n} times`),
  web: (n) => `Read ${n} ${n === 1 ? "page" : "pages"}`,
  shell: (n) => `Ran ${n} ${n === 1 ? "command" : "commands"}`,
  read: (n) => `Read ${n} ${n === 1 ? "file" : "files"}`,
  edit: (n) => `Edited ${n} ${n === 1 ? "file" : "files"}`,
  agent: (n) => `Asked ${n} ${n === 1 ? "agent" : "agents"}`,
  other: (n) => `Used ${n} ${n === 1 ? "tool" : "tools"}`,
};

/** "Ran 3 commands · Read 2 files" in first-seen order; a stopped step is counted too. */
export function stepsSummary(tools: ToolPart[]): string {
  const counts = new Map<ToolCategory, number>();
  for (const t of tools) {
    const c = toolCategory(t.toolName);
    counts.set(c, (counts.get(c) ?? 0) + 1);
  }
  const text = [...counts].map(([c, n]) => DONE[c](n)).join(" · ");
  const live = tools.filter(isLive).length;
  return live ? `${text} · ${live} running` : text;
}
