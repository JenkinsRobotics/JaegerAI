import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MOCK_AGENTS } from "../api/mock";
import type { Agent } from "../api/types";
import { AgentDetails } from "./AgentDetails";
import { visible } from "./agentsLogic";

const render = (agent: Agent) => renderToStaticMarkup(
  <AgentDetails agent={agent} onOpenHistory={() => {}} onClose={() => {}} />);

describe("AgentDetails skills and tools", () => {
  const swe: Agent = {
    id: "agent:swe", name: "swe", display_name: "SWE", role: "reverse-engineer",
    skills: [{ id: "rea", name: "REA", description: "Reverse-engineers an app look-only.", source_path: "skills/rea/SKILL.md" }],
    allowed_tools: ["shell", "otool"],
  };
  it("lists each skill's name and description, and the allowed tools", () => {
    const html = render(swe);
    expect(html).toContain("Reverse engineer");
    expect(html).toContain('<span class="jg-skill__name">REA</span>');
    expect(html).toContain('<span class="jg-skill__desc">Reverse-engineers an app look-only.</span>');
    expect(html).toContain('<li class="jg-tool-chip">shell</li><li class="jg-tool-chip">otool</li>');
  });
  it("keeps source_path to a tooltip, never in the visible text", () => {
    const html = render(swe);
    expect(html).toContain('title="skills/rea/SKILL.md"');
    expect(html.replace(/title="[^"]*"/g, "")).not.toContain("SKILL.md");
  });
  it("omits the sections when an agent has no skills or tools (today's gateway)", () => {
    const html = render({ id: "agent:x", name: "x", role: "specialist" });
    expect(html).not.toContain("Skills");
    expect(html).not.toContain("Tools");
  });
  it("mock agents carry the proposed roles and stay visible", () => {
    const roles = new Set(MOCK_AGENTS.filter(visible).map((a) => a.role));
    expect(roles).toEqual(new Set(["lead", "builder", "designer", "researcher", "reverse-engineer", "reviewer"]));
    expect(MOCK_AGENTS.filter(visible).every((a) => (a.skills?.length ?? 0) > 0)).toBe(true);
  });
});

it('uses explicit access authority metadata rather than primary pin or execution role', () => {
  const local = {scope:'local_operator',sharing_supported:false,membership_management_supported:false,grouping_grants_access:false,reason:'No cross-account membership authority is configured'} as const;
  const html = render({id:'owned-bot',name:'Owned',role:'lead',primary:true,pinned:true,access:local});
  expect(html).toContain('do not grant membership or share conversations');
  expect(html).toContain('Cross-account sharing is unavailable');
  expect(render({id:'unknown-owner',name:'Other',role:'lead',primary:true,pinned:true})).toContain('does not advertise');
});
