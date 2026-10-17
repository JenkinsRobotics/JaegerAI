/* Trivial markdown for the stand-in renderer: paragraphs, "- " and "1. "
 * lists, fenced code blocks (with Copy), **bold**, `code` and links. It builds
 * React elements only, never HTML strings. The shared chat widget brings VS
 * Code's markdown renderer. */
import { useState, type ReactNode } from "react";

type Handlers = { onCopy?: (text: string) => void; onOpen?: (url: string) => void };

const SAFE_URL = /^https?:\/\//i;

function inline(text: string, h: Handlers): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|https?:\/\/[^\s)]+)/g).filter(Boolean).map((chunk, i) => {
    if (chunk.startsWith("**") && chunk.endsWith("**")) return <strong key={i}>{chunk.slice(2, -2)}</strong>;
    if (chunk.startsWith("`") && chunk.endsWith("`")) return <code key={i}>{chunk.slice(1, -1)}</code>;
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(chunk);
    const [label, url] = link ? [link[1], link[2]] : [chunk, chunk];
    if ((link || SAFE_URL.test(chunk)) && SAFE_URL.test(url)) {
      return (
        <a key={i} href={url} className="jg-link" onClick={(e) => { if (h.onOpen) { e.preventDefault(); h.onOpen(url); } }} target="_blank" rel="noopener noreferrer">
          {label}
        </a>
      );
    }
    return chunk;
  });
}

function CodeBlock({ code, lang, onCopy }: { code: string; lang: string; onCopy?: (text: string) => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="jg-codeblock">
      <div className="jg-codeblock__bar">
        <span>{lang}</span>
        {onCopy && (
          <button type="button" className="jg-codeblock__copy" aria-label="Copy code"
            onClick={() => { onCopy(code); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
            {copied ? "Copied" : "Copy"}
          </button>
        )}
      </div>
      <pre><code>{code}</code></pre>
    </div>
  );
}

function blocks(text: string, h: Handlers): ReactNode[] {
  const out: ReactNode[] = [];
  // Fenced code first, so blank lines inside a fence never split it.
  text.split(/(```[^\n]*\n[\s\S]*?(?:```|$))/g).forEach((piece, i) => {
    const fence = /^```([^\n]*)\n([\s\S]*?)(?:```)?$/.exec(piece);
    if (fence) { out.push(<CodeBlock key={`c${i}`} lang={fence[1].trim()} code={fence[2].replace(/\n$/, "")} onCopy={h.onCopy} />); return; }
    piece.split(/\n{2,}/).filter((b) => b.trim()).forEach((block, j) => {
      const lines = block.split("\n").filter((l) => l.trim());
      const key = `${i}.${j}`;
      if (lines.every((l) => /^\s*[-*] /.test(l))) {
        out.push(<ul key={key}>{lines.map((l, k) => <li key={k}>{inline(l.replace(/^\s*[-*] /, ""), h)}</li>)}</ul>);
      } else if (lines.every((l) => /^\s*\d+[.)] /.test(l))) {
        out.push(<ol key={key}>{lines.map((l, k) => <li key={k}>{inline(l.replace(/^\s*\d+[.)] /, ""), h)}</li>)}</ol>);
      } else {
        out.push(<p key={key}>{inline(block, h)}</p>);
      }
    });
  });
  return out;
}

export function MiniMarkdown({ text, onCopy, onOpen }: { text: string } & Handlers) {
  return <>{blocks(text, { onCopy, onOpen })}</>;
}
