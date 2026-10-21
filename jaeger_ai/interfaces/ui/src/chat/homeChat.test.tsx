import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { HistoryPanel } from "../agents/HistoryPanel";
import { MockSource } from "../api/mock";
import { mockHome } from "../api/mockHome";
import { PostMessage, postChipText, SummaryCard, summaryLine } from "./HomeEntries";
import type { HomeEntry, HomeSessions } from "./homeSession";
import { MinimalChat } from "./MinimalChat";
import { WebHost } from "./webHost";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const links = { onOpen: vi.fn(), onCopy: vi.fn() };
type Summary = Extract<HomeEntry, { kind: "summary" }>;
type Post = Extract<HomeEntry, { kind: "post" }>;

async function mount(node: React.ReactNode) {
  const el = document.createElement("div");
  document.body.append(el);
  const root = createRoot(el);
  await act(async () => { root.render(node); });
  return { el, done: () => { act(() => root.unmount()); el.remove(); } };
}
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

describe("SummaryCard", () => {
  const entry: Summary = { kind: "summary", id: "s", text: "Planned **four** specialists.", count: 48 };
  it("reads 'Earlier conversation summarized · Show' and reveals the summary on Show", async () => {
    expect(summaryLine(entry)).toBe("Earlier conversation summarized (48 messages)");
    const { el, done } = await mount(<SummaryCard entry={entry} links={links} />);
    expect(el.textContent).toContain("Earlier conversation summarized (48 messages)·Show");
    expect(el.querySelector(".jg-summary__text")).toBeNull();
    await act(async () => { el.querySelector<HTMLButtonElement>(".jg-summary__toggle")!.click(); });
    expect(el.querySelector(".jg-summary__text strong")?.textContent).toBe("four");
    expect(el.querySelector(".jg-summary__toggle")?.getAttribute("aria-expanded")).toBe("true");
    done();
  });
});

describe("PostMessage (handoff and task results as real messages)", () => {
  const handoff: Post = { kind: "post", id: "p", post: "handoff", sender: { id: "agent:swe", name: "SWE" }, text: "Fixed it.", handoffId: "h9", childSessionId: "s-child" };
  it("shows the sender's avatar and name, the text, the handoff chip and the child chat link", async () => {
    const open = vi.fn();
    const openChat = vi.fn();
    const { el, done } = await mount(<PostMessage entry={handoff} links={links} onOpenHandoff={open} onOpenChat={openChat} />);
    expect(el.querySelector(".jg-post__who .jg-avatar")).toBeTruthy();
    expect(el.querySelector(".jg-post__name")?.textContent).toBe("SWE");
    expect(el.querySelector(".jg-post__body")?.textContent).toContain("Fixed it.");
    expect(el.querySelector(".jg-post__chip")?.textContent).toBe("Handoff result");
    await act(async () => { el.querySelector<HTMLButtonElement>("button.jg-post__chip")!.click(); });
    expect(open).toHaveBeenCalledWith("h9");
    await act(async () => { el.querySelector<HTMLButtonElement>(".jg-post__link")!.click(); });
    expect(openChat).toHaveBeenCalledWith("s-child");
    done();
  });
  it("renders a handoff request with its own chip, opening the same handoff", () => {
    const request: Post = { ...handoff, post: "handoff_request", sender: { id: "native:jaeger", name: "Jaeger" }, text: "Asked SWE to fix it." };
    expect(postChipText(request)).toBe("Handoff request");
    const html = renderToStaticMarkup(<PostMessage entry={request} links={links} onOpenHandoff={() => {}} />);
    expect(html).toContain("jg-post--handoff_request");
    expect(html).toContain('<button type="button" class="jg-post__chip">Handoff request</button>');
  });
  it("opens a durable task artifact reference without turning the message path into a grant",async()=>{
    const open=vi.fn();const task:Post={...handoff,post:"task_result",taskId:"owned-task",handoffId:undefined};
    const {el,done}=await mount(<PostMessage entry={task} links={links} onOpenTaskArtifacts={open}/>);
    await act(async()=>[...el.querySelectorAll('button')].find(b=>b.textContent==='Open task artifacts')!.click());
    expect(open).toHaveBeenCalledWith('owned-task');done();
  });
  it("labels task results; no handoff button, no chat link without a child session", () => {
    const task: Post = { ...handoff, post: "task_result", handoffId: undefined, childSessionId: undefined, taskId: "t5", status: "failed" };
    expect(postChipText(task)).toBe("Task result · Failed");
    const html = renderToStaticMarkup(<PostMessage entry={task} links={links} onOpenChat={() => {}} />);
    expect(html).toContain("jg-post--task_result is-failed");
    expect(html).not.toContain("<button");
  });
});

describe("home chat in MinimalChat", () => {
  const host = () => {
    const h = new WebHost(new MockSource());
    h.home = mockHome(new MockSource());
    h.listAgents = async () => [];
    return h;
  };
  it("renders the newest page with posted results, then loads the older page on scroll-up, keeping the reader's place", async () => {
    const { el, done } = await mount(<MinimalChat host={host()} sessionId="s-native:jaeger" />);
    await flush();
    expect(el.querySelectorAll('[data-sender="post"]').length).toBe(3);
    expect(el.querySelector('[data-sender="summary"]')).toBeNull();
    expect(el.textContent).toContain("Show earlier messages");
    const scroller = el.querySelector<HTMLDivElement>(".jg-chat__scroll")!;
    Object.defineProperty(scroller, "scrollHeight", { configurable: true, get: () => el.querySelectorAll("section").length * 100 });
    Object.defineProperty(scroller, "clientHeight", { configurable: true, get: () => 300 });
    const before = el.querySelectorAll("section").length;
    scroller.scrollTop = 20;
    await act(async () => { scroller.dispatchEvent(new Event("scroll")); });
    await flush();
    const after = el.querySelectorAll("section").length;
    expect(after).toBeGreaterThan(before);
    expect(el.querySelector("section")?.querySelector('[data-sender="summary"]')).toBeTruthy(); // the summary heads the chat
    expect(scroller.scrollTop).toBe((after - before) * 100 + 20);
    expect(el.textContent).not.toContain("Show earlier messages"); // start of the chat reached
    done();
  });
  it("opens History from the agent pill's menu", async () => {
    const h = host();
    h.openHistory = vi.fn();
    const { el, done } = await mount(<MinimalChat host={h} sessionId="s-native:jaeger" />);
    await flush();
    await act(async () => { el.querySelector<HTMLButtonElement>(".jg-agent-pill")!.click(); });
    const item = [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((n) => n.textContent === "History");
    expect(item).toBeTruthy();
    await act(async () => { item!.click(); });
    expect(h.openHistory).toHaveBeenCalledWith("native:jaeger");
    done();
  });
});

describe("HistoryPanel", () => {
  it("lists older chats and opens one read-only (no composer)", async () => {
    const home = mockHome(new MockSource());
    const { el, done } = await mount(<HistoryPanel agentId="native:jaeger" agentName="Jaeger" home={home} onClose={() => {}} />);
    await flush();
    const rows = el.querySelectorAll<HTMLButtonElement>(".jg-history__row");
    expect([...rows].map((r) => r.querySelector(".jg-history__title")?.textContent)).toEqual(["Sidebar rollout note", "Overnight build failure"]);
    await act(async () => { rows[0].click(); });
    await flush();
    expect(el.querySelector(".jg-details__who strong")?.textContent).toBe("Sidebar rollout note");
    expect(el.textContent).toContain("Read-only");
    expect(el.querySelector(".jg-history__view")?.textContent).toContain("Your old chats are under History.");
    expect(el.querySelector("textarea, form")).toBeNull();
    await act(async () => { el.querySelector<HTMLButtonElement>('[aria-label="Back to history"]')!.click(); });
    expect(el.querySelectorAll(".jg-history__row").length).toBe(2);
    done();
  });
  it("says so when there's no history", async () => {
    const empty: HomeSessions = { mode: "mock", home: async () => "h", page: async () => ({ sessionId: "h", turns: [], entries: {} }), history: async () => [], read: async () => ({ sessionId: "h", turns: [], entries: {} }) };
    const { el, done } = await mount(<HistoryPanel agentId="a" agentName="SWE" home={empty} onClose={() => {}} />);
    await flush();
    expect(el.textContent).toContain("No older chats");
    done();
  });
});
