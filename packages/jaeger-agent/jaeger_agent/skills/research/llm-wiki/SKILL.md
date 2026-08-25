---
name: llm-wiki
description: "Build or maintain an interlinked Markdown knowledge base using the LLM Wiki pattern. Use when the user wants durable synthesized notes, cross-references, contradiction tracking, and incremental source ingestion."
license: MIT
metadata:
  jros:
    version: 3.0.0
    lifecycle: optional
    skill-class: first-class
    platforms: [linux, macos, windows]
    requires-tools: [read_file, write_file, search_files, web_extract, execute_code]
    tags: [wiki, knowledge-base, research, markdown]
    category: research
---

# LLM WIKI

## SOP

1. Resolve the wiki root and read its index, conventions, and recent log before
   changing anything.
2. For a new wiki, choose a narrow domain and initialize index/conventions/log.
3. Ingest one source at a time; preserve source URL/date and separate quotation,
   sourced fact, inference, and unresolved contradiction.
4. Search existing pages before creating a new entity or concept page.
5. Read `references/imported-guide.md` only for schema, page thresholds, update
   policy, and advanced maintenance.
6. Update backlinks, index, and append-only log in the same operation.

## ERROR HATCH

If the wiki is inconsistent or its conventions are missing, stop writes and
produce a repair plan. Never overwrite conflicting claims to make them agree.

## DONE WHEN

The source is represented once, cross-links resolve, contradictions remain
visible, and the index and log reflect the change.
