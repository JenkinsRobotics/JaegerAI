---
name: hermes-agent-skill-authoring
description: "Author or edit a JROS SKILL.md. Alias of skill-builder — load this or skill-builder for creating, rewriting, or tightening a skill, or fixing one that names tools that don't exist."
version: 3.0.0
archived: true
platforms: [macos, linux, windows]
requires_tools: [write_file, read_file, patch, list_skills, benchmark_skill, record_skill_revision]
metadata:
  jros:
    tags: [skills, authoring, skill-md, conventions, meta]
    category: software-development
    related_skills: [skill-builder, self-improvement, writing-plans]
---

# AUTHORING JROS SKILLS

This skill is an alias. The live authoring SOP is `skill-builder`.

## SOP

1. `use_skill(name="skill-builder")`.
2. For the 8-point checklist + frontmatter schema:
   `read_file` the skill-builder file `references/authoring-standard.md`.
3. Follow skill-builder Flow A (create), B (review), or C (improve).
   Do not invent a second authoring process.

## HARD RULE

Never invent a tool name. Verify with `describe_tool(name=...)` /
`list_tools(query=...)` before writing it into a SKILL.md.

## ERROR HATCH

- Unsure a tool exists → `describe_tool(name=...)`. If it errors, the
  tool is not registered. Reroute to `terminal` / `execute_code` /
  `web_search`. Never guess.
- A newly-written skill is invisible this session → expected (loader
  caches at start). Verify with `read_file` on the exact path.

## DONE WHEN

The target SKILL.md meets skill-builder's 8 points, every named tool
exists in the registry, and `record_skill_revision` logged the change.
