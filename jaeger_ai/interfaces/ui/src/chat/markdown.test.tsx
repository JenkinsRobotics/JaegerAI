import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { highlight, resolveLang } from "./highlight";
import { Markdown, fenceClosed, splitBlocks } from "./Markdown";

const html = (text: string) => renderToStaticMarkup(<Markdown text={text} onCopy={() => {}} onOpen={() => {}} />);

describe("markdown (react-markdown + GFM)", () => {
  it("renders tables, task lists, strikethrough and autolinks", () => {
    const out = html("| a | b |\n| - | - |\n| 1 | 2 |\n\n- [x] done\n- [ ] todo\n\n~~old~~ see https://example.com");
    expect(out).toContain('<div class="jg-md__table"><table>');
    expect(out).toContain("<td>1</td>");
    expect(out).toMatch(/<input[^>]*type="checkbox"[^>]*checked/);
    expect(out).toContain("<del>old</del>");
    expect(out).toContain('href="https://example.com"');
  });

  it("never renders raw HTML or unsafe links or remote images", () => {
    const out = html('<script>alert(1)</script>\n\nA [x](javascript:alert(1)) and <b onclick="x">b</b>\n\n![pic](https://example.com/a.png)');
    expect(out).not.toContain("<script");
    expect(out).toContain("&lt;script&gt;"); // shown as text
    expect(out).not.toMatch(/href="javascript:/);
    expect(out).not.toContain("<b ");
    expect(out).toContain('<span class="jg-link jg-link--inert">x</span>');
    expect(out).not.toContain("<img");
    expect(out).toContain('href="https://example.com/a.png"');
  });

  it("marks a still-streaming fence as not closed (no highlighting yet)", () => {
    expect(html("```ts\nconst a = 1;\n```")).toContain('data-closed="true"');
    expect(html("```ts\nconst a = 1;")).toContain('data-closed="false"');
    expect(fenceClosed("```ts\nx\n```")).toBe(true);
    expect(fenceClosed("```ts\nx")).toBe(false);
    expect(fenceClosed("    indented")).toBe(true);
  });
});

describe("splitBlocks", () => {
  it("splits at blank lines but keeps fences, lists and continuations whole", () => {
    const text = "Intro\n\n```sh\necho a\n\necho b\n```\n\n1. one\n\n2. two\n   more\n\nEnd";
    const blocks = splitBlocks(text);
    expect(blocks).toHaveLength(4);
    expect(blocks[1]).toContain("echo a\n\necho b");
    expect(blocks[2]).toContain("2. two");
    expect(blocks.join("\n")).toBe(text);
  });
  it("an unclosed fence swallows the rest (streaming)", () => {
    expect(splitBlocks("a\n\n```\ncode\n\nmore")).toHaveLength(2);
  });
});

describe("lazy Shiki", () => {
  it("resolves aliases and only the small language set", () => {
    expect(resolveLang("ts")).toBe("typescript");
    expect(resolveLang("bash")).toBe("shellscript");
    expect(resolveLang("cobol")).toBeUndefined();
  });
  it("highlights with the CSS-variables theme", async () => {
    const out = await highlight("const a = 1;", "ts");
    expect(out).toContain('class="shiki');
    expect(out).toContain("var(--shiki-");
    expect(await highlight("x", "cobol")).toBeNull();
  });
});
