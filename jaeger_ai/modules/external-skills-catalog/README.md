# external-skills-catalog — CATALOG ONLY, do NOT copy skills wholesale into the repo

Job: a catalog of external skill packs found in Ai work, to import ONE skill at a time, after a license check, if that skill actually helps Jaeger. Jaeger already has a large skill system (jaeger-agent: ~107 skills, skill_tree in JaegerAI), so this module is a catalog, not a second skill system.

Source, NOT copied:
- Desktop "Ai  work " / JaegerAI_Archive/skills/ — skills_codex/ (31+ folders listed: claude-cowork--anthropic-skills, apollo, bio-research, brand-voice, common-room, cowork-plugin-management, customer-support, daily-brief, data, design, engineering, enterprise-search, finance, human-resources, legal, marketing, operations, product-management, productivity, sales, slack-by-salesforce, plus openai-bundled--sites/visualize, openai-curated, openai-curated-remote--openai-templates/plugin-management, openai-primary-runtime--documents/pdf/presentations/spreadsheets), blockchain/, gaming/, social-media/, yuanbao/.
- These are third-party skill packs (Anthropic Claude Cowork, OpenAI curated/bundled/primary-runtime, plus other skill folders). Their licenses are NOT the project's license, and were NOT verified in this audit. Do NOT copy them into JaegerAI or jaeger-agent, do NOT present them as Jaeger skills, and do NOT import them in bulk.

Import rule (matches Jaeger v1 skill learning: one skill at a time):
- Pick ONE skill, check its license + SKILL.md, check it does not duplicate an existing Jaeger skill, check it does not require a cloud service that breaks TRUST.md, then import that ONE skill via the skill registry, test it alone, then move on.
- Skills that help Jenkins Robotics first (YouTube pipeline, project graph, NAS intake, engineering) come before generic productivity/finance/HR/legal skills. Blockchain/gaming/social-media/yuanbao skills are catalog entries only, not v1.

Test to run when code-run is available: import ONE catalog skill, run its test alone, verify it does not break existing skills, remove it cleanly if it fails.
