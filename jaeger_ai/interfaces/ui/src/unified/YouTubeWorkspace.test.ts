import { describe, expect, it } from "vitest";
import { parseBrief, productionPrompt } from "./YouTubeWorkspace";
const brief = { version: 1, title: "Build an AI tool", audience: "Beginners", format: "Short · 30–60 seconds", goal: "Run it themselves", notes: ["https://example.com", "Draft", "", "", "", ""], reviewed: [true,false,false,false,false,false] };
describe("portable production brief", () => {
  it("round trips the brief and excludes unknown fields", () => {
    expect(parseBrief(JSON.parse(JSON.stringify({...brief, credentials:"never export"})))).toEqual(brief);
  });
  it("rejects malformed or unbounded imports", () => {
    for(const value of [null, {...brief,version:2}, {...brief,notes:[]}, {...brief,reviewed:["true"]}, {...brief,goal:"x".repeat(20001)}]) expect(()=>parseBrief(value)).toThrow();
  });
  it("includes earlier stage context and approval boundaries in a handoff", () => {
    const prompt=productionPrompt(parseBrief(brief),1);
    expect(prompt).toContain("Current stage: Script");
    expect(prompt).toContain("https://example.com");
    expect(prompt).toContain("Ask before paid generation or publishing");
  });
});
