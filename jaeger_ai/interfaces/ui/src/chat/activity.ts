/* Observable activity descriptions. Gateway receipts own execution state; these
 * pure helpers describe it for the live line and collapsed transcript groups. */
import type { ChatPart, ChatTurn } from "./host";

export type ToolPart = Extract<ChatPart, { kind: "toolInvocation" }>;
export type ToolCategory = "search" | "web" | "browser" | "shell" | "read" | "fileSearch" | "list" | "image" | "imageGeneration" | "edit" | "agent" | "computer" | "skill" | "audio" | "plan" | "toolDiscovery" | "integration" | "other";

type ActivityDescription = { running:string; present:string; past:string; done:(count:number)=>string };
const counted = (singular:string, plural=singular+"s") => (n:number) => `${n} ${n===1?singular:plural}`;
/** The one display catalog, usable by future activity surfaces without a second vocabulary. */
export const ACTIVITY_CATALOG:Record<ToolCategory,ActivityDescription> = {
  search:{running:"Searching the web…",present:"Searching",past:"Searched",done:n=>n===1?"Searched the web":`Searched the web ${n} times`},
  web:{running:"Reading a page…",present:"Reading",past:"Read",done:n=>`Read ${counted("page")(n)}`},
  browser:{running:"Using the browser…",present:"Using",past:"Used",done:n=>n===1?"Used the browser":`Used the browser ${n} times`},
  shell:{running:"Running commands…",present:"Running",past:"Ran",done:n=>`Ran ${counted("command")(n)}`},
  read:{running:"Reading files…",present:"Reading",past:"Read",done:n=>`Read ${counted("file")(n)}`},
  fileSearch:{running:"Searching files…",present:"Searching",past:"Searched",done:n=>n===1?"Searched files":`Searched files ${n} times`},
  list:{running:"Listing files…",present:"Listing",past:"Listed",done:n=>`Listed ${counted("directory","directories")(n)}`},
  image:{running:"Viewing an image…",present:"Viewing",past:"Viewed",done:n=>n===1?"Viewed an image":`Viewed ${n} images`},
  imageGeneration:{running:"Generating images…",present:"Generating with",past:"Called",done:n=>`Called ${counted("image-generation tool")(n)}`},
  edit:{running:"Writing to a file…",present:"Editing",past:"Edited",done:n=>`Edited ${counted("file")(n)}`},
  agent:{running:"Calling an agent tool…",present:"Calling",past:"Called",done:n=>`Called ${counted("agent tool")(n)}`},
  computer:{running:"Using the computer…",present:"Using",past:"Used",done:n=>`Used ${counted("computer tool")(n)}`},
  skill:{running:"Using skill tools…",present:"Using",past:"Used",done:n=>`Used ${counted("skill tool")(n)}`},
  audio:{running:"Processing audio…",present:"Using",past:"Used",done:n=>`Used ${counted("audio tool")(n)}`},
  plan:{running:"Updating the plan…",present:"Updating",past:"Updated",done:n=>n===1?"Updated the plan":`Updated the plan ${n} times`},
  toolDiscovery:{running:"Discovering tools…",present:"Looking up",past:"Looked up",done:n=>n===1?"Looked up tools":`Looked up tools ${n} times`},
  integration:{running:"Using an integration…",present:"Using",past:"Used",done:n=>`Used ${counted("integration tool")(n)}`},
  other:{running:"Waiting on results…",present:"Using",past:"Used",done:n=>`Used ${counted("tool")(n)}`},
};

/** Only known operation names imply a family. Unknown tools retain a generic label.
 * Provider namespaces do not prevent recognized operations from being described. */
export function toolCategory(name:string):ToolCategory {
  const full=name.trim().toLowerCase(),n=full.split("__").at(-1)??full;
  if(/\s/.test(full))return "shell";
  if(/(^|[_.:])(call_agent|ask_agent|handoff|delegate|framework_delegate|spawn_agent|wait_agent|send_message_to_agent|send_message_to_thread|followup_task|interrupt_agent|resume_agent|close_agent)([_.:]|$)/.test(n))return "agent";
  if(/(^|[_.:])(update_plan|plan_update)([_.:]|$)/.test(n))return "plan";
  if(/(^|[_.:])(load_tools|list_tools|describe_tool|tool_search)([_.:]|$)/.test(n))return "toolDiscovery";
  if(/(^|[_.:])(use_skill|load_skill|read_skill|list_skills|reload_skills|skill_note|skill_notes|request_skill_review|record_skill_revision)([_.:]|$)/.test(n))return "skill";
  if(/(^|[_.:])(text_to_speech|speech_to_text|transcribe|transcribe_audio|listen|speak|record_audio|insta360_record_audio)([_.:]|$)/.test(n))return "audio";
  if(/(image_generate|generate_image|imagegen)/.test(n))return "imageGeneration";
  if(/(computer_use|macos_computer|cua_repl|take_screenshot|capture_screen)/.test(full))return "computer";
  if((n==="search" && !full.startsWith("mcp__")) || /(^|[_.:])(web_?search|search_web|internet_search|google|brave|bing)([_.:]|$)/.test(n))return "search";
  if(/(^|[_.:])(search_files|file_search|grep|glob|find_files|find_in_files)([_.:]|$)/.test(n))return "fileSearch";
  if(/(^|[_.:])(list_skill_dir|list_dir|list_directory|list_files|ls)([_.:]|$)/.test(n))return "list";
  if(/(browser|browse)/.test(n))return "browser";
  if(/(^|[.:])(fetch|fetch_url|web_?read|read_url|open_url|read_page|http_get|scrape|crawl)$/.test(n))return "web";
  if(/(shell|bash|zsh|terminal|exec|run_command|command|execute_code|run_)/.test(n))return "shell";
  if(/(write|edit|patch|apply|replace|append_file|copy_file|create_file|delete_file|move_file)/.test(n))return "edit";
  if(/(view_image|image_view|inspect_image|vision_analyze|look_at|screenshot)/.test(n))return "image";
  if(/(^|[_.:])(read_file|file_read|view_file|cat|get_file_contents)([_.:]|$)/.test(n))return "read";
  if(full.startsWith("mcp__") || /(^|[_.:])(list_plugins|setup_plugin)([_.:]|$)/.test(n))return "integration";
  return "other";
}

export const CODING="Writing code…";
export const NEEDS_INPUT="Needs your OK";
/** Neutral words report a live turn without claiming unobserved progress. */
export const thinkingPhrase=(_turnId:string):string=>"Thinking…";
export const workingPhrase=(_turnId:string):string=>"Working…";

const isLive=(p:ToolPart)=>p.state==="streaming" || p.state==="executing" || p.state==="waitingForConfirmation";
const CODE_FILE=/\.(tsx?|jsx?|mjs|cjs|py|swift|rs|go|rb|java|kt|c|cc|cpp|h|hpp|cs|sh|zsh|css|scss|html|sql|lua|php)$/i;

/** The file, command, URL or query a step works on, when its input names one. */
export function toolTarget(part:Pick<ToolPart,"toolName"|"input">):string|undefined {
  const input=part.input;
  if(typeof input==="string")return input.trim()||undefined;
  const command=/\s/.test(part.toolName.trim())?part.toolName.trim():undefined;
  if(!input || typeof input!=="object")return command;
  const o=input as Record<string,unknown>;
  for(const key of ["path","file_path","image_path","file","filename","target","command","cmd","url","query","q","pattern","agent","agent_id","name"]){
    const value=o[key];
    if(typeof value==="string" && value.trim())return value.trim();
    if(Array.isArray(value) && value.length && value.every(v=>typeof v==="string"))return value.join(" ");
  }
  return command;
}

const TERMINAL_VERBS:Partial<Record<ToolPart["state"],string>>={cancelled:"Stopped",failed:"Failed",denied:"Denied",rejected:"Rejected",unsupported:"Unsupported",unknown:"Outcome unknown for"};
/** No failure/unknown receipt is rendered with an in-progress or success verb. */
export function stepLine(part:ToolPart):{verb:string;target:string;mono:boolean} {
  const category=toolCategory(part.toolName),target=toolTarget(part);
  const verb=TERMINAL_VERBS[part.state]??(part.state==="waitingForConfirmation"?"Awaiting approval for":part.state==="streaming"?"Preparing":part.state==="completed"?ACTIVITY_CATALOG[category].past:ACTIVITY_CATALOG[category].present);
  return {verb,target:target??part.toolName,mono:!target || !["search","fileSearch","skill"].includes(category) || /[\/\\]/.test(target)};
}

/** An unclosed ``` or ~~~ fence: the reply is writing code right now. */
export function inOpenFence(text:string):boolean {
  let open=false;
  for(const line of text.split("\n"))if(/^\s{0,3}(```|~~~)/.test(line))open=!open;
  return open;
}

/** Latest observable activity; approvals and questions block only while pending. */
export function activityPhrase(turn:Pick<ChatTurn,"turnId"|"parts">,agentName?:(id:string)=>string|undefined):string {
  const parts=turn.parts;
  if(parts.some(p=>p.kind==="confirmation" && !p.decision) || parts.some(p=>p.kind==="toolInvocation" && p.state==="waitingForConfirmation"))return NEEDS_INPUT;
  if(parts.some(p=>p.kind==="question" && !p.chosenId && (!p.status || p.status==="pending")))return "Waiting for your answer…";
  for(let i=parts.length-1;i>=0;i--){
    const p=parts[i];
    if(p.kind==="toolInvocation" && isLive(p)){
      if(p.state==="streaming")return "Preparing a tool call…";
      const category=toolCategory(p.toolName);
      if(category==="edit" && CODE_FILE.test(toolTarget(p)??""))return CODING;
      return ACTIVITY_CATALOG[category].running;
    }
    if(p.kind==="handoff"){
      const name=agentName?.(p.agentId)??p.agentName;
      if(p.direction==="from")return `Reply received from ${name}.`;
      const returned=parts.slice(i+1).some(q=>q.kind==="handoff" && q.direction==="from" && q.handoffId===p.handoffId);
      if(returned)continue;
      if(p.status==="pending_approval")return `Waiting for approval to message ${name}…`;
      if(p.status==="delivered")return `Waiting for ${name}…`;
      if(p.status==="execution_unknown")return `Agent message outcome unknown for ${name}.`;
      if(["failed","denied","rejected","cancelled"].includes(p.status??""))return `Agent message ${p.status} for ${name}.`;
      return `Agent message requested for ${name}…`;
    }
    if(p.kind==="progress" && p.message)return p.message;
    if(p.kind==="error" || p.kind==="warning")return p.message;
    if(p.kind==="thinking")return p.durationMs===undefined?thinkingPhrase(turn.turnId):workingPhrase(turn.turnId);
    if(p.kind==="markdownContent" && p.text)return inOpenFence(p.text)?CODING:workingPhrase(turn.turnId);
    if(p.kind==="plan")return "Plan updated.";
    if(p.kind==="checkpoint")return "Progress checkpoint received.";
    if(p.kind==="userGuidance")return "Follow-up sent to the active turn.";
    if(p.kind==="toolInvocation")return TERMINAL_VERBS[p.state]?`${p.toolName}: ${p.state==="unknown"?"outcome unknown":p.state}.`:workingPhrase(turn.turnId);
  }
  return "Waiting for agent progress…";
}

/** Successful call counts, not inferred image counts, agent lifecycles or artifacts. */
export function stepsSummary(tools:ToolPart[]):string {
  const unique=[...new Map(tools.map(tool=>[tool.callId,tool])).values()];
  const counts=new Map<ToolCategory,number>();
  for(const tool of unique){if(tool.state!=="completed")continue;const category=toolCategory(tool.toolName);counts.set(category,(counts.get(category)??0)+1);}
  const waiting=unique.filter(t=>t.state==="waitingForConfirmation").length;
  const live=unique.filter(t=>t.state==="streaming" || t.state==="executing").length;
  const outcomes=["failed","denied","rejected","unsupported","cancelled","unknown"].flatMap(state=>{const n=unique.filter(t=>t.state===state).length;return n?[`${n} ${state}`]:[];});
  return [...[...counts].map(([category,n])=>ACTIVITY_CATALOG[category].done(n)),...outcomes,live?`${live} running`:"",waiting?`${waiting} waiting for your OK`:""].filter(Boolean).join(" · ");
}
