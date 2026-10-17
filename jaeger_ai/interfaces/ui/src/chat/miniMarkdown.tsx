/* Trivial markdown for the mock stand-in: paragraphs, "- " lists, **bold**,
 * `code`. It builds React elements only, never HTML strings. The shared chat
 * widget brings VS Code's markdown renderer. */
import type { ReactNode } from "react";

function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean).map((chunk, i) => {
    if (chunk.startsWith("**") && chunk.endsWith("**")) return <strong key={i}>{chunk.slice(2, -2)}</strong>;
    if (chunk.startsWith("`") && chunk.endsWith("`")) return <code key={i}>{chunk.slice(1, -1)}</code>;
    return chunk;
  });
}

export function MiniMarkdown({ text }: { text: string }) {
  return (
    <>
      {text.split(/\n{2,}/).map((block, i) => {
        const lines = block.split("\n");
        if (lines.every((l) => /^\s*[-*] /.test(l))) {
          return <ul key={i}>{lines.map((l, j) => <li key={j}>{inline(l.replace(/^\s*[-*] /, ""))}</li>)}</ul>;
        }
        return <p key={i}>{inline(block)}</p>;
      })}
    </>
  );
}
