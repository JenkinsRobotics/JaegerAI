/* Chat markdown (Jenkins Robotics, 2026-10-17, original): react-markdown + GitHub-flavoured markdown
 * (tables, task lists, strikethrough, autolinks). Raw HTML is never rendered. Links open through the host
 * (http/https only); fenced code gets its language, Copy, and lazy Shiki highlighting once the fence is
 * closed. The text is split into top-level blocks and each finished block is memoized, so a streaming reply
 * re-renders only its last block. */
import { memo, useEffect, useRef, useState, type MutableRefObject, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { highlight, resolveLang } from "./highlight";

export type MarkdownHandlers = { onCopy?: (text: string) => void; onOpen?: (url: string) => void };
type HandlersRef = MutableRefObject<MarkdownHandlers>;

const SAFE_URL = /^https?:\/\//i;
const FENCE_OPEN = /^\s{0,3}(`{3,}|~{3,})/;
const FENCE_CLOSE = /^\s{0,3}(`{3,}|~{3,})\s*$/;
const LIST_ITEM = /^\s*([-*+]|\d+[.)])\s/;

/** Top-level blocks: split at blank lines, never inside a fence, keeping lists and indented
 * continuations together. Joining the blocks with "\n" gives back the input. */
export function splitBlocks(text: string): string[] {
  const blocks: string[] = [];
  let cur: string[] = [];
  let fence: string | null = null;
  let blank = false;
  const flush = () => { if (cur.length) blocks.push(cur.join("\n")); cur = []; };
  for (const line of text.split("\n")) {
    if (fence) {
      cur.push(line);
      const close = FENCE_CLOSE.exec(line);
      if (close && close[1][0] === fence[0] && close[1].length >= fence.length) fence = null;
      continue;
    }
    if (!line.trim()) { blank = true; cur.push(line); continue; }
    const open = FENCE_OPEN.exec(line);
    if (blank && cur.length) {
      const continues = !open && (/^\s/.test(line) || (LIST_ITEM.test(line) && cur.some((l) => LIST_ITEM.test(l))));
      if (!continues) flush();
    }
    blank = false;
    cur.push(line);
    if (open) fence = open[1];
  }
  flush();
  return blocks;
}

/** A fenced block's source is closed when its last line is a closing fence. */
export function fenceClosed(source: string): boolean {
  const lines = source.replace(/\n+$/, "").split("\n");
  if (!FENCE_OPEN.test(lines[0] ?? "")) return true; // indented code: nothing streams into it
  return lines.length > 1 && FENCE_CLOSE.test(lines[lines.length - 1]);
}

type HastNode = { type: string; value?: string; tagName?: string; properties?: { className?: unknown }; children?: HastNode[] };
const textOf = (n: HastNode): string => n.type === "text" ? (n.value ?? "") : (n.children ?? []).map(textOf).join("");

function CodeBlock({ code, lang, closed, handlers }: { code: string; lang: string; closed: boolean; handlers: HandlersRef }) {
  const [html, setHtml] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const copiedTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => { if (copiedTimer.current) clearTimeout(copiedTimer.current); }, []);
  const supported = Boolean(resolveLang(lang));
  useEffect(() => {
    setHtml(null);
    if (!closed || !supported) return;
    let live = true; const controller = new AbortController();
    highlight(code, lang, controller.signal).then((h) => { if (live) setHtml(h); }, () => { /* stay plain */ });
    return () => { live = false; controller.abort(); };
  }, [code, lang, closed, supported]);
  const onCopy = handlers.current.onCopy;
  return (
    <div className="jg-codeblock" data-closed={closed ? "true" : "false"} data-highlighted={html ? "true" : "false"}>
      <div className="jg-codeblock__bar">
        <span>{lang}</span>
        {onCopy && (
          <button type="button" className="jg-codeblock__copy" aria-label="Copy code"
            onClick={() => { handlers.current.onCopy?.(code); setCopied(true); if (copiedTimer.current) clearTimeout(copiedTimer.current); copiedTimer.current = setTimeout(() => setCopied(false), 1500); }}>
            {copied ? "Copied" : "Copy"}
          </button>
        )}
      </div>
      {html
        ? <div className="jg-codeblock__shiki" dangerouslySetInnerHTML={{ __html: html }} />
        : <pre><code>{code}</code></pre>}
    </div>
  );
}

function components(source: string, handlers: HandlersRef): Components {
  return {
    a({ href, children }) {
      const url = href ?? "";
      if (!SAFE_URL.test(url)) return <span className="jg-link jg-link--inert">{children}</span>;
      return (
        <a href={url} className="jg-link" target="_blank" rel="noopener noreferrer"
          onClick={(e) => { const open = handlers.current.onOpen; if (open) { e.preventDefault(); open(url); } }}>
          {children}
        </a>
      );
    },
    // No remote images in the transcript: show the alt text as a link instead.
    img({ src, alt }) {
      const url = typeof src === "string" ? src : "";
      const label = alt || url || "image";
      return SAFE_URL.test(url)
        ? <a href={url} className="jg-link" target="_blank" rel="noopener noreferrer"
            onClick={(e) => { const open = handlers.current.onOpen; if (open) { e.preventDefault(); open(url); } }}>{label}</a>
        : <span>{label}</span>;
    },
    table({ children }) {
      return <div className="jg-md__table"><table>{children}</table></div>;
    },
    pre({ node, children }) {
      const el = node as unknown as HastNode & { position?: { start: { offset?: number }; end: { offset?: number } } };
      const code = el?.children?.find((c) => c.type === "element" && c.tagName === "code");
      if (!code) return <pre>{children}</pre>;
      const cls = code.properties?.className;
      const classes = Array.isArray(cls) ? cls.map(String) : typeof cls === "string" ? cls.split(" ") : [];
      const lang = classes.find((c) => c.startsWith("language-"))?.slice("language-".length) ?? "";
      const start = el.position?.start.offset, end = el.position?.end.offset;
      const closed = start === undefined || end === undefined ? true : fenceClosed(source.slice(start, end));
      return <CodeBlock code={textOf(code).replace(/\n$/, "")} lang={lang} closed={closed} handlers={handlers} />;
    },
  };
}

const remarkPlugins = [remarkGfm];

const Block = memo(function Block({ text, handlers }: { text: string; handlers: HandlersRef }) {
  return <ReactMarkdown remarkPlugins={remarkPlugins} components={components(text, handlers)}>{text}</ReactMarkdown>;
}, (a, b) => a.text === b.text && a.handlers === b.handlers);

export const MARKDOWN_UNITS_MAX = 65536;
const PLAIN_PORTION = 16383; // Boundary adjustment may add one UTF-16 unit.
/** Large messages remain intact in the transcript owner. Bound only the DOM and
 * parser work; all portions and full-source Copy remain explicitly available. */
function PlainPortions({text, handlers}: {text:string;handlers:HandlersRef}) {
  const [page,setPage] = useState(0);
  const pages = Math.ceil(text.length / PLAIN_PORTION), current = Math.min(page, pages - 1);
  const boundary = (offset:number) => offset > 0 && /[\uDC00-\uDFFF]/.test(text[offset] ?? '') && /[\uD800-\uDBFF]/.test(text[offset - 1]) ? offset - 1 : offset;
  const start = boundary(current * PLAIN_PORTION), end = boundary(Math.min(text.length, (current + 1) * PLAIN_PORTION));
  return <section aria-label="Large message bounded preview"><p>Large message shown as plain text in bounded portions. Full source is retained. Portion {current + 1} of {pages}.</p><pre aria-label="Large message plain portion" style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{text.slice(start,end)}</pre><button type="button" disabled={current===0} onClick={()=>setPage(current-1)}>Previous message portion</button><button type="button" disabled={current===pages-1} onClick={()=>setPage(current+1)}>Next message portion</button>{handlers.current.onCopy&&<button type="button" onClick={()=>handlers.current.onCopy?.(text)}>Copy full message</button>}</section>;
}

export function Markdown({ text, onCopy, onOpen }: { text: string } & MarkdownHandlers): ReactNode {
  const handlers = useRef<MarkdownHandlers>({ onCopy, onOpen });
  handlers.current = { onCopy, onOpen };
  if (text.length > MARKDOWN_UNITS_MAX) return <PlainPortions text={text} handlers={handlers}/>;
  return <>{splitBlocks(text).map((block, i) => <Block key={i} text={block} handlers={handlers} />)}</>;
}
