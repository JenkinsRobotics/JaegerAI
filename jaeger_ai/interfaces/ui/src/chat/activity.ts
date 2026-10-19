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
  if (/(read|view|cat|list_dir|ls|grep|glob|search_files|find)/.test(n) || /^list_|_dir$/.test(n)) return "read";
  if (/(call_agent|handoff|delegate|ask_agent)/.test(n)) return "agent";
  return "other";
}

const RUNNING: Record<ToolCategory, string> = {
  search: "Searching the web…",
  web: "Reading a page…",
  shell: "Running commands…",
  read: "Reading files…",
  edit: "Writing to a file…",
  agent: "Checking with another agent…",
  other: "Waiting on results…",
};

const THINKING = ["Thinking…", "Working it out…", "Putting it together…"] as const;
const WORKING = ["Working on it…", "Making headway…", "Getting there…", "Sorting it out…", "Plugging away…"] as const;
export const CODING = "Writing code…";
export const NEEDS_INPUT = "Needs your OK";

function pick<T extends readonly string[]>(list: T, seed: string): T[number] {
  let h = 0;
  for (let i = 0; i < seed.length; i += 1) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return list[h % list.length];
}

/** Stable per turn, so the phrase does not flicker between renders. */
export const thinkingPhrase = (turnId: string): string => pick(THINKING, turnId);
/** Generic "still busy" phrase, also stable per turn. */
export const workingPhrase = (turnId: string): string => pick(WORKING, `w:${turnId}`);

const isLive = (p: ToolPart) => p.state === "streaming" || p.state === "executing" || p.state === "waitingForConfirmation";
const CODE_FILE = /\.(tsx?|jsx?|mjs|cjs|py|swift|rs|go|rb|java|kt|c|cc|cpp|h|hpp|cs|sh|zsh|css|scss|html|sql|lua|php)$/i;

/** The file, command, URL or query a step works on, when its input names one. */
export function toolTarget(part: Pick<ToolPart, "toolName" | "input">): string | undefined {
  const input = part.input;
  if (typeof input === "string") return input.trim() || undefined;
  const command = /\s/.test(part.toolName.trim()) ? part.toolName.trim() : undefined; // "npm run build"
  if (!input || typeof input !== "object") return command;
  const o = input as Record<string, unknown>;
  for (const key of ["path", "file_path", "file", "filename", "target", "command", "cmd", "url", "query", "q", "pattern", "agent", "agent_id"]) {
    const v = o[key];
    if (typeof v === "string" && v.trim()) return v.trim();
    if (Array.isArray(v) && v.length && v.every((x) => typeof x === "string")) return v.join(" ");
  }
  return command;
}

const PAST: Record<ToolCategory, string> = { search: "Searched", web: "Read", shell: "Ran", read: "Read", edit: "Edited", agent: "Asked", other: "Used" };
const NOW: Record<ToolCategory, string> = { search: "Searching", web: "Reading", shell: "Running", read: "Reading", edit: "Editing", agent: "Asking", other: "Using" };

/** One step in the fold: a verb plus what it worked on ("Ran" + "npm run build"); the tool name stands in for a missing target. */
export function stepLine(part: ToolPart): { verb: string; target: string; mono: boolean } {
  const category = toolCategory(part.toolName);
  const target = toolTarget(part);
  const verb = part.state === "cancelled" ? "Stopped" : part.state === "waitingForConfirmation" ? "Wants to run"
    : part.state === "completed" ? PAST[category] : NOW[category];
  if (!target) return { verb, target: part.toolName, mono: true };
  // Queries read as words; paths, commands and URLs as code.
  return { verb, target, mono: category !== "search" || /[\/\\]/.test(target) };
}

/** An unclosed ``` or ~~~ fence: the reply is writing code right now. */
export function inOpenFence(text: string): boolean {
  let open = false;
  for (const line of text.split("\n")) if (/^\s{0,3}(```|~~~)/.test(line)) open = !open;
  return open;
}

/** The progress line for a pending turn, from its latest part. */
export function activityPhrase(turn: Pick<ChatTurn, "turnId" | "parts">, agentName?: (id: string) => string | undefined): string {
  const parts = turn.parts;
  if (parts.some((p) => p.kind === "confirmation") || parts.some((p) => p.kind === "toolInvocation" && p.state === "waitingForConfirmation")) {
    return NEEDS_INPUT;
  }
  for (let i = parts.length - 1; i >= 0; i -= 1) {
    const p = parts[i];
    if (p.kind === "toolInvocation" && isLive(p)) {
      const category = toolCategory(p.toolName);
      if (category === "edit" && CODE_FILE.test(toolTarget(p) ?? "")) return CODING;
      return RUNNING[category];
    }
    if (p.kind === "handoff" && p.direction === "to") {
      // Still out with that agent unless it already came back.
      const back = parts.slice(i + 1).some((q) => q.kind === "handoff" && q.direction === "from" && q.handoffId === p.handoffId);
      if (!back) return `Checking with ${agentName?.(p.agentId) ?? p.agentName}…`;
    }
    if (p.kind === "progress" && p.message) return p.message.endsWith("…") ? p.message : `${p.message}…`;
    if (p.kind === "thinking") return p.durationMs === undefined ? thinkingPhrase(turn.turnId) : workingPhrase(turn.turnId);
    if (p.kind === "markdownContent" && p.text) return inOpenFence(p.text) ? CODING : workingPhrase(turn.turnId);
    if (p.kind === "toolInvocation" || p.kind === "handoff") return workingPhrase(turn.turnId);
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

/** "Ran 3 commands · Read 2 files" in first-seen order; a stopped step is counted too, one awaiting approval is not. */
export function stepsSummary(tools: ToolPart[]): string {
  const counts = new Map<ToolCategory, number>();
  const waiting = tools.filter((t) => t.state === "waitingForConfirmation").length;
  for (const t of tools) {
    if (t.state === "waitingForConfirmation") continue;
    const c = toolCategory(t.toolName);
    counts.set(c, (counts.get(c) ?? 0) + 1);
  }
  const live = tools.filter((t) => t.state === "streaming" || t.state === "executing").length;
  return [...[...counts].map(([c, n]) => DONE[c](n)), live ? `${live} running` : "", waiting ? `${waiting} waiting for your OK` : ""]
    .filter(Boolean).join(" · ");
}
