import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { SessionRow } from "../api/types";
import { ChatList } from "./ChatList";
import { chatTitle, shortTime, visibleChats } from "./chats";
import { agentSlug, newChatItems } from "./NewChatMenu";

const row = (id: string, at: number, extra: Partial<SessionRow> = {}): SessionRow =>
  ({ session_id: id, title: "New chat", message_count: 2, last_activity_at: at, ...extra });

describe("an agent's chats", () => {
  it("keeps every chat with messages, newest first; empty ones only while open; never archived ones", () => {
    const rows = [row("old", 10), row("empty", 30, { message_count: 0 }), row("new", 20), row("gone", 40, { archived: true })];
    expect(visibleChats(rows).map((r) => r.session_id)).toEqual(["new", "old"]);
    expect(visibleChats(rows, "empty").map((r) => r.session_id)).toEqual(["empty", "new", "old"]);
  });

  it("titles a generic chat from its last message", () => {
    expect(chatTitle(row("a", 1, { title: "Launch plan" }))).toBe("Launch plan");
    expect(chatTitle(row("b", 1, { title: "New Conversation", last_message_preview: "Everyday replied pong" }))).toBe("Everyday replied pong");
    expect(chatTitle(row("c", 1, { message_count: 0 }))).toBe("New chat");
    expect(chatTitle(row("d", 1, { last_message_preview: "x".repeat(80) })).length).toBe(48);
  });

  it("shows short times", () => {
    const now = new Date(2026, 9, 17, 17, 0).getTime();
    expect(shortTime(now / 1000 - 30, now)).toBe("now");
    expect(shortTime(now / 1000 - 300, now)).toBe("5m");
    expect(shortTime(now / 1000 - 86_400, now)).toBe("Yesterday");
  });

  it("renders a row per chat with the open one marked, and collapses long lists", () => {
    const rows = Array.from({ length: 8 }, (_, i) => row(`s${i}`, 100 - i, { title: `Chat ${i}` }));
    const html = renderToStaticMarkup(<ChatList rows={rows} openId="s1" onOpen={() => {}} onRename={() => {}} onArchive={() => {}} />);
    expect(html.match(/jg-chat-row__title/g)?.length).toBe(5);
    expect(html).toContain('aria-current="page"');
    expect(html).toContain("Show 3 more");
  });
});

describe("New chat menu", () => {
  it("offers a fresh chat with each agent, then Create agent", () => {
    const items = newChatItems([{ id: "native:jaeger", name: "jaeger", role: "lead" }, { id: "native:everyday", name: "everyday", display_name: "Everyday" }]);
    expect(items.map((i) => i.label)).toEqual(["New chat with Jaeger", "New chat with Everyday", "Create agent…"]);
    expect(items[2].separatorBefore).toBe(true);
  });

  it("makes an id-safe agent name", () => {
    expect(agentSlug("  Research Lead! ")).toBe("research-lead");
    expect(agentSlug("!!!")).toBe("");
  });
});
