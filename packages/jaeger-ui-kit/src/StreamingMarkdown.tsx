/**
 * Zero-jitter Streaming Markdown renderer powered by OpenCode's Patchmark (MIT).
 * Uses Patchmark's streaming block parser + tail healing to avoid partial fence/heading pops.
 */

import { useMemo } from "react";
import { createMarkdownStream, renderBlocksToHtml } from "./patchmark";

export interface StreamingMarkdownProps {
  text: string;
  streaming?: boolean;
}

export function StreamingMarkdown({ text, streaming = false }: StreamingMarkdownProps) {
  const html = useMemo(() => {
    const stream = createMarkdownStream({ heal: streaming });
    const frame = stream.update(text || "", { streaming });
    return renderBlocksToHtml(frame.blocks);
  }, [text, streaming]);

  return (
    <div
      className="jg-markdown"
      // Patchmark escapes all raw HTML by default via escapeHtml()
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
