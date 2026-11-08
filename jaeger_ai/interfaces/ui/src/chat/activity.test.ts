import { describe, expect, it } from "vitest";
import type { ChatPart } from "./host";
import { CODING, NEEDS_INPUT, activityPhrase, inOpenFence, stepsSummary, thinkingPhrase, toolCategory, toolTarget, workingPhrase, stepLine, ACTIVITY_CATALOG, type ToolPart } from "./activity";

const tool = (toolName: string, state: ToolPart["state"] = "completed", callId = toolName): ToolPart =>
  ({ kind: "toolInvocation", callId, toolName, input: {}, state });

describe("activity", () => {
  it("classifies Jaeger's tool names", () => {
    expect(toolCategory("web_search")).toBe("search");
    expect(toolCategory("browser")).toBe("browser");
    expect(toolCategory("shell")).toBe("shell");
    expect(toolCategory("terminal")).toBe("shell");
    expect(toolCategory("execute_code")).toBe("shell");
    expect(toolCategory("npm run build")).toBe("shell");
    expect(toolCategory("read_file")).toBe("read");
    expect(toolCategory("search_files")).toBe("fileSearch");
    expect(toolCategory("list_skill_dir")).toBe("list");
    expect(toolCategory("view_image")).toBe("image");
    expect(toolCategory("write_file")).toBe("edit");
    expect(toolCategory("edit_file")).toBe("edit");
    expect(toolCategory("call_agent")).toBe("agent");
    expect(toolCategory("weather")).toBe("other");
  });

  it("names the live activity", () => {
    expect(activityPhrase({ turnId: "t", parts: [tool("web_search", "executing")] })).toBe("Searching the web…");
    expect(activityPhrase({ turnId: "t", parts: [tool("read_file"), tool("shell", "executing", "c2")] })).toBe("Running commands…");
    expect(activityPhrase({ turnId: "t", parts: [tool("git commit", "waitingForConfirmation")] })).toBe(NEEDS_INPUT);
    expect(activityPhrase({ turnId: "t", parts: [{ kind: "progress", message: "Looking at the roster" }] })).toBe("Looking at the roster");
    const to = { kind: "handoff", handoffId: "h", agentId: "native:research", agentName: "Research", count: 1, direction: "to" } as const;
    expect(activityPhrase({ turnId: "t", parts: [to] })).toBe("Agent message requested for Research…");
    expect(activityPhrase({ turnId: "t", parts: [to, { ...to, direction: "from" }] })).toBe("Reply received from Research.");
  });

  it("covers every activity category from the latest part", () => {
    const at = (parts: Parameters<typeof activityPhrase>[0]["parts"]) => activityPhrase({ turnId: "t", parts });
    expect(at([{ kind: "thinking", text: "hmm" }])).toBe(thinkingPhrase("t"));
    expect(at([{ kind: "thinking", text: "hmm", durationMs: 900 }])).toBe(workingPhrase("t"));
    expect(at([{ kind: "markdownContent", text: "Sure, here" }])).toBe(workingPhrase("t"));
    expect(at([{ kind: "markdownContent", text: "Here:\n```bash\necho hi" }])).toBe(CODING);
    expect(at([{ kind: "markdownContent", text: "Here:\n```bash\necho hi\n```\nDone" }])).toBe(workingPhrase("t"));
    expect(at([{ ...tool("browser", "executing") }])).toBe("Using the browser…");
    expect(at([{ ...tool("read_file", "executing") }])).toBe("Reading files…");
    expect(at([{ ...tool("view_image", "executing") }])).toBe("Viewing an image…");
    expect(at([{ ...tool("write_file", "executing"), input: { path: "notes/todo.md" } }])).toBe("Writing to a file…");
    expect(at([{ ...tool("write_file", "executing"), input: { path: "src/app.tsx" } }])).toBe(CODING);
    expect(at([{ ...tool("weather", "executing") }])).toBe("Waiting on results…");
    expect(at([tool("shell")])).toBe(workingPhrase("t"));
  });

  it("finds a step's target and open fences", () => {
    expect(toolTarget({ toolName: "read_file", input: { path: "/tmp/a.txt" } })).toBe("/tmp/a.txt");
    expect(toolTarget({ toolName: "shell", input: { command: ["ls", "-la"] } })).toBe("ls -la");
    expect(toolTarget({ toolName: "npm run build", input: null })).toBe("npm run build");
    expect(toolTarget({ toolName: "weather", input: {} })).toBeUndefined();
    expect(inOpenFence("a\n~~~\nb")).toBe(true);
    expect(inOpenFence("```\nb\n```")).toBe(false);
  });

  it("thinks with a phrase that is stable per turn", () => {
    expect(thinkingPhrase("abc")).toBe(thinkingPhrase("abc"));
    expect(thinkingPhrase("abc")).toBe("Thinking…");
    expect(workingPhrase("abc")).toBe("Working…");
    expect(activityPhrase({ turnId: "abc", parts: [{ kind: "thinking", text: "" }] })).toBe(thinkingPhrase("abc"));
  });

  it("summarises steps in first-seen order", () => {
    expect(stepsSummary([tool("shell"), tool("read_file", "completed", "r1"), tool("bash", "completed", "s2"),
      tool("read_file", "completed", "r2"), tool("terminal", "completed", "s3")])).toBe("Ran 3 commands · Read 2 files");
    expect(stepsSummary([tool("web_search")])).toBe("Searched the web");
    expect(stepsSummary([tool("view_image")])).toBe("Viewed an image");
    expect(stepsSummary([tool("write_file"), tool("shell", "executing", "s")])).toBe("Edited 1 file · 1 running");
    expect(stepsSummary([tool("npm run build"), tool("git commit", "waitingForConfirmation", "g")])).toBe("Ran 1 command · 1 waiting for your OK");
  });
});

it("does not count rejected/failed edits as files edited", () => {
 const item: ToolPart={kind:"toolInvocation",callId:"rejected",toolName:"write_file",input:{path:"fixture"},state:"rejected"};
 expect(stepsSummary([item,{...item,callId:"failed",state:"failed"}])).toBe("1 failed · 1 rejected");
});

it("does not claim the agent is thinking before any progress arrives", () => {
  expect(activityPhrase({turnId: "admitted", parts: []})).toBe("Waiting for agent progress…");
});


it("maps the concrete tool catalog to distinct observable activity families", () => {
 const families:Record<string, ReturnType<typeof toolCategory>>={search_files:"fileSearch",list_skill_dir:"list",computer_use:"computer",macos_computer:"computer",image_generate:"imageGeneration",text_to_speech:"audio",listen:"audio",update_plan:"plan",load_tools:"toolDiscovery",describe_tool:"toolDiscovery",list_skills:"skill",use_skill:"skill",framework_delegate:"agent",wait_agent:"agent",send_message_to_thread:"agent",mcp__github__list_issues:"integration",mcp__files__read_file:"read"};
 for(const [name,family] of Object.entries(families))expect(toolCategory(name),name).toBe(family);
 expect(stepsSummary([tool("search_files"),tool("list_skill_dir"),tool("browser"),tool("computer_use"),tool("load_tools"),tool("text_to_speech"),tool("image_generate"),tool("update_plan")])).toBe("Searched files · Listed 1 directory · Used the browser · Used 1 computer tool · Looked up tools · Used 1 audio tool · Called 1 image-generation tool · Updated the plan");
 expect(Object.keys(ACTIVITY_CATALOG)).toHaveLength(18);
});

it("uses terminal verbs for every non-success outcome", () => {
 const outcomes={failed:"Failed",denied:"Denied",rejected:"Rejected",unsupported:"Unsupported",cancelled:"Stopped",unknown:"Outcome unknown for"} as const;
 for(const [state,verb] of Object.entries(outcomes)){
  const item=tool("shell",state as ToolPart["state"]);expect(stepLine(item).verb).toBe(verb);expect(activityPhrase({turnId:"t",parts:[item]})).not.toContain("Running");
 }
 expect(stepLine(tool("shell","streaming")).verb).toBe("Preparing");expect(activityPhrase({turnId:"t",parts:[tool("shell","streaming")]})).toBe("Preparing a tool call…");
});

it("stops waiting when an approval or question has been answered", () => {
 const approved={kind:"confirmation",callId:"c",title:"Run",message:"Run",decision:"approve"} as const;
 const answered:Extract<ChatPart,{kind:"question"}>={kind:"question",callId:"q",title:"Which?",options:[],status:"answered"};
 expect(activityPhrase({turnId:"t",parts:[approved,answered,tool("shell","executing")]})).toBe("Running commands…");
 expect(activityPhrase({turnId:"t",parts:[{...answered,status:"pending"}]})).toBe("Waiting for your answer…");
});

it("does not infer agent execution or completion from a failed or unconfirmed handoff", () => {
 const to={kind:"handoff",handoffId:"h",agentId:"a",agentName:"Research",count:1,direction:"to"} as const;
 expect(activityPhrase({turnId:"t",parts:[{...to,status:"failed"}]})).toBe("Agent message failed for Research.");
 expect(activityPhrase({turnId:"t",parts:[{...to,status:"execution_unknown"}]})).toBe("Agent message outcome unknown for Research.");
 expect(stepsSummary([tool("call_agent")])).toBe("Called 1 agent tool");
});

it("counts each call identity once and retains its latest outcome", () => {
 expect(stepsSummary([tool("shell","executing","same"),tool("shell","completed","same")])).toBe("Ran 1 command");
 expect(stepsSummary([tool("write_file","executing","same"),tool("write_file","failed","same")])).toBe("1 failed");
});

it("does not claim an integration search or repository fetch is web browsing",()=>{
 expect(toolCategory('mcp__github__search')).toBe('integration');
 expect(toolCategory('mcp__github__fetch_commit')).toBe('integration');
 expect(toolCategory('mcp__web__fetch')).toBe('web');
});
