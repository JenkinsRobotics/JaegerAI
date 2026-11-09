# Chat activity description catalog

Scope: the shared browser/native chat's observable activity descriptions. Model-written progress sentences are open-ended; they cannot be listed as a finite string catalog. This maps observable event families, preserving Jaeger's Gateway and authority model.

## Codex reference

Installed artifact: `com.openai.codex` 26.1103.41825. The bounded inventory contains **211 unique activity-related localization keys** from four selected JavaScript members. These include plural, running/completed and accessibility variants; 211 keys does not mean 211 states. The scoped inventory is [CODEX_ACTIVITY_REFERENCE.json](CODEX_ACTIVITY_REFERENCE.json).

ASAR SHA-256: `766faa8a3da8f6d6902c751d5b6b29395a6c5bf3c966ef7f8ca3f629d931df85`.
REA evidence: `ev_e47eecea9fc671423e7a199347142b116737955e8b895561225958f75950d4be`; summary: `ev_4489e3079b62ab14f5309cf762a0e9391aca7e90e2e8f67b94a50259fba0f2bc`.
The selected semantic graph was bounded/partial. This establishes shipped strings, not execution or reachability of every branch. No private conversations or credentials were used.

Public protocol reference: [Codex App Server](https://learn.chatgpt.com/docs/app-server).

## Jaeger display catalog

`src/chat/activity.ts` exports `ACTIVITY_CATALOG`, the single display vocabulary used by `activityPhrase`, `stepLine` and `stepsSummary`. Current Gateway `tool.started`, `tool.completed` and `tool.failed` receipts supply identity and outcome. Known operation names inside provider namespaces remain recognizable; unknown tools retain generic descriptions.

| Family | Actual operation examples | Live description | Successful collapsed description |
| --- | --- | --- | --- |
| Web search | `web_search`, `search_web` | Searching the web | Searched the web |
| Page read | `fetch`, `read_url`, `read_page` | Reading a page | Read N pages |
| Browser | `browser`, browser operations | Using the browser | Used the browser |
| Commands | `terminal`, `execute_code`, `shell` | Running commands | Ran N commands |
| File reads | `read_file`, `get_file_contents` | Reading files | Read N files |
| File search | `search_files`, `grep`, `glob` | Searching files | Searched files |
| Directory lists | `list_skill_dir`, `list_directory` | Listing files | Listed N directories |
| Image inspection | `view_image`, `vision_analyze` | Viewing an image | Viewed N images |
| Image generation | `image_generate` | Generating images | Called N image-generation tools |
| File changes | `write_file`, `patch`, `copy_file` | Writing to a file / Writing code | Edited N files |
| Agent tools | `call_agent`, `framework_delegate`, `wait_agent` | Calling an agent tool | Called N agent tools |
| Computer | `computer_use`, `macos_computer`, `cua_repl` | Using the computer | Used N computer tools |
| Skills | `use_skill`, `list_skills`, `reload_skills` | Using skill tools | Used N skill tools |
| Audio | `text_to_speech`, `listen`, transcription tools | Processing audio | Used N audio tools |
| Plans | `update_plan` | Updating the plan | Updated the plan |
| Tool discovery | `load_tools`, `describe_tool`, `list_tools` | Discovering tools | Looked up tools |
| Integrations | other namespaced MCP calls, plugin operations | Using an integration | Used N integration tools |
| Other | unknown operation | Waiting on results | Used N tools |

Counts measure successful calls. A generic tool receipt cannot establish the number of generated images, loaded schemas, delivered messages or started/finished agents. The expanded row retains the recorded target. Replayed projections of one call ID count once; failed, denied, rejected, unsupported, cancelled and unknown outcomes are separate.

## State mapping

| Evidence | Description |
| --- | --- |
| Tool arguments streaming | Preparing a tool call; never Running before execution |
| Undecided confirmation / waiting tool | Needs your OK |
| Pending question | Waiting for your answer |
| Decided confirmation / answered or expired question | Does not keep the live line waiting |
| Executing tool | Family-specific present tense |
| Completed tool | Family-specific past tense |
| Failed, denied, rejected, unsupported | Explicit corresponding terminal verb |
| Cancelled | Stopped |
| Unknown | Outcome unknown; never success or running |
| Reasoning started | Thinking |
| No more specific live progress | Working; no random making-headway claim |
| Progress event | Actual producer text, without adding an in-progress ellipsis |
| Plan / checkpoint | Plan updated / Progress checkpoint received |
| Durable steering event | Follow-up sent to the active turn |
| Handoff requested / pending approval | Explicit request/approval wording |
| Delivered handoff | Waiting for the named agent |
| Failed, denied or unconfirmed handoff | Exact delivery outcome |
| Reply handoff | Reply received from the named agent |

## Remaining parity boundaries

Codex also ships Created/Messaged/Resumed/Closed agent labels, initialization/running/shutdown/finished-with-errors states, background terminal status and elapsed command labels, loaded-tool counts, compaction and optimization interruption, automatic approval-review declines, permission requests, worktree initialization, remote tasks, model rerouting, automation updates and realtime transcripts. Jaeger's current shared `ChatPart` stream does not carry every corresponding lifecycle distinction. These labels must be connected to authoritative events before being displayed; a generic agent tool success cannot fabricate Spawned/Finished N agents.

`ActivityFold` already displays recorded reasoning duration. This helper adds no artificial Worked-for duration: full turn time needs an explicit start/end pair. Live `approval.resolved` events carry the authoritative request ID and settle the original confirmation without replacing its description. Local decisions and history checks update the same part.

Voice controls separately display real capture readiness, microphone level and playback state through the platform adapter. An audio tool receipt does not establish audibility. Build, deployment and actual-client acceptance are checked separately.

## Focused verification

Tests cover registered tool families, search versus directory/read counts, terminal verbs, pending-only approvals/questions, failed/unconfirmed agent delivery, preparing versus executing, neutral wording and call-ID deduplication.
