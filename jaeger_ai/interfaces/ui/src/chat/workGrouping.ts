// Import the existing IDE reducer, not a second copy of its grouping rules.
import "../../../ide/media/timeline.js";
import type {ChatPart} from "./host";

export function partitionChatParts(parts: ChatPart[]) {
  const kinds: Record<string,string> = {
    markdownContent: "answer", thinking: "reasoning", toolInvocation: "tool",
  };
  const rows = parts.map((part,index)=>({kind:part.kind==="markdownContent" ? part.role === "commentary" ? "commentary" : part.role === "final" ? "final" : "answer" : kinds[part.kind] ?? part.kind,part,index}));
  return globalThis.JaegerTimeline.partitionTurn(rows);
}
