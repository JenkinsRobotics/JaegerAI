/**
 * Markdown Renderer with Syntax Highlighting
 *
 * Ported from OpenClaw/Hermes pattern.
 * Renders markdown with:
 * - Syntax highlighted code blocks (Prism)
 * - Tables, task lists, strikethrough (GFM)
 * - Copy button on code blocks
 * - Links with external indicator
 */

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Copy, Check, ExternalLink } from 'lucide-react'
import { useState, useCallback } from 'react'
import { cn } from '../lib/utils'

interface MarkdownRendererProps {
  content: string
  className?: string
  dark?: boolean
}

// Copy button for code blocks
function CopyButton({ code }: { code: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [code])

  return (
    <button
      onClick={handleCopy}
      className="absolute right-2 top-2 rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
      title="Copy code"
    >
      {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
    </button>
  )
}

export function MarkdownRenderer({ content, className, dark = true }: MarkdownRendererProps) {
  const codeStyle = dark ? oneDark : oneLight

  return (
    <div className={cn('prose prose-sm dark:prose-invert max-w-none', className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Code blocks with syntax highlighting
          code({ node, inline, className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '')
            const code = String(children).replace(/\n$/, '')

            if (!inline && match) {
              return (
                <div className="relative group">
                  <div className="absolute right-2 top-2 z-10 opacity-0 group-hover:opacity-100 transition-opacity">
                    <CopyButton code={code} />
                  </div>
                  <div className="absolute left-2 top-2 z-10 text-xs text-muted-foreground font-mono">
                    {match[1]}
                  </div>
                  <SyntaxHighlighter
                    style={codeStyle}
                    language={match[1]}
                    PreTag="div"
                    className="rounded-lg !mt-2 !mb-4"
                    customStyle={{
                      margin: 0,
                      borderRadius: '0.5rem',
                      padding: '2.5rem 1rem 1rem',
                    }}
                    {...props}
                  >
                    {code}
                  </SyntaxHighlighter>
                </div>
              )
            }

            // Inline code
            return (
              <code
                className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.875em] text-foreground"
                {...props}
              >
                {children}
              </code>
            )
          },

          // Tables
          table({ children }) {
            return (
              <div className="overflow-x-auto my-4">
                <table className="min-w-full divide-y divide-border border border-border rounded-lg">
                  {children}
                </table>
              </div>
            )
          },
          thead({ children }) {
            return <thead className="bg-muted">{children}</thead>
          },
          th({ children }) {
            return (
              <th className="px-4 py-2 text-left text-sm font-semibold text-foreground">
                {children}
              </th>
            )
          },
          td({ children }) {
            return (
              <td className="px-4 py-2 text-sm text-muted-foreground border-t border-border">
                {children}
              </td>
            )
          },

          // Links with external indicator
          a({ href, children }) {
            const isExternal = href?.startsWith('http')
            return (
              <a
                href={href}
                target={isExternal ? '_blank' : undefined}
                rel={isExternal ? 'noopener noreferrer' : undefined}
                className="text-primary hover:underline inline-flex items-center gap-1"
              >
                {children}
                {isExternal && <ExternalLink className="h-3 w-3" />}
              </a>
            )
          },

          // Blockquotes
          blockquote({ children }) {
            return (
              <blockquote className="border-l-4 border-primary/50 pl-4 italic text-muted-foreground my-4">
                {children}
              </blockquote>
            )
          },

          // Task lists (checkboxes)
          input({ type, checked, ...props }) {
            if (type === 'checkbox') {
              return (
                <input
                  type="checkbox"
                  checked={checked}
                  className="mr-2 rounded border-border"
                  readOnly
                  {...props}
                />
              )
            }
            return <input type={type} {...props} />
          },

          // Horizontal rule
          hr() {
            return <hr className="my-6 border-border" />
          },

          // Headings
          h1({ children }) {
            return <h1 className="text-2xl font-bold mt-6 mb-4">{children}</h1>
          },
          h2({ children }) {
            return <h2 className="text-xl font-bold mt-5 mb-3">{children}</h2>
          },
          h3({ children }) {
            return <h3 className="text-lg font-semibold mt-4 mb-2">{children}</h3>
          },

          // Paragraphs
          p({ children }) {
            return <p className="my-3 leading-relaxed">{children}</p>
          },

          // Lists
          ul({ children }) {
            return <ul className="my-3 ml-6 list-disc space-y-1">{children}</ul>
          },
          ol({ children }) {
            return <ol className="my-3 ml-6 list-decimal space-y-1">{children}</ol>
          },
          li({ children }) {
            return <li className="leading-relaxed">{children}</li>
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// Streaming Markdown Renderer (for live responses)
// ─────────────────────────────────────────────────────────────

interface StreamingMarkdownProps extends MarkdownRendererProps {
  isStreaming?: boolean
}

export function StreamingMarkdownRenderer({ isStreaming, ...props }: StreamingMarkdownProps) {
  return (
    <>
      <MarkdownRenderer {...props} />
      {isStreaming && (
        <span className="inline-flex items-center gap-1 text-muted-foreground">
          <span className="animate-pulse">●</span>
          <span className="text-sm">Generating...</span>
        </span>
      )}
    </>
  )
}
