# Jaeger capability equivalence: assistant tools and everyday agency

Assessment date: 2026-09-23. Scope: the capabilities exposed to the auditing
assistant in this session, compared with inspected Jaeger source. This is not
an inventory of proprietary model internals or a claim that tool parity yields
equal reasoning quality. Provider access, credentials, permissions, dependencies,
and actual model performance require separate qualification.

Purpose: give Jaeger suitable equivalents for observing, researching, coding,
operating applications, completing work, and checking outcomes. Preserve existing
features; reuse owners and tools rather than create a second runtime or registry.

## Evidence levels

- **Present:** an implementation or packaged procedure was located. Not a live pass.
- **Partial:** an implementation exists, but the inspected contract has a gap or
  the complete owner/client path is not established.
- **Unestablished:** a suitable end-to-end equivalent was not established in this
  bounded inspection. This does not assert absence from the entire repository.
- **Qualified:** reserved for a recorded execution of the acceptance task through
  the production owner and relevant client. No row below receives this label merely
  because a file, tool registration, mock test, or documentation exists.

Paths below are relative to the repository. `agent/` in the source column means
`packages/jaeger-agent/jaeger_agent/`; it is a documentation abbreviation, not a
new directory or import namespace.

## Capability matrix

| ID | Capability available to this assistant | Jaeger implementation/equivalent | Assessment | Required acceptance task |
| --- | --- | --- | --- | --- |
| C01 | Interpret requests, plan, reason, revise | `agent/loop/jaeger_agent.py`, `agent/adapters/`, `jaeger_ai/core/models/router.py` | Present; quality depends on selected model; routing alone does not establish competence | Complete a multi-step repair with an unexpected failure; preserve the objective while revising the approach. |
| C02 | Discover available tools and read their schemas | `agent/tools/meta.py`, `agent/skill_registry/toolset_scoping.py`, existing tool registry | Present; actual visibility/availability must be checked in the owner | Begin with a scoped tool set, discover and load a needed tool, call it, and explain an unavailable dependency accurately. |
| C03 | Read files and search a repository | `agent/tools/files.py`: `read_file`, `search_files`, directory tools; terminal | Present; permitted project context matters | Find a symbol, read its callers, and cite the correct current file and location without reading the entire checkout. |
| C04 | Apply precise source edits | `agent/tools/files.py`: `patch`, `write_file`, read tracking/project binding | Present; not identical to unified-diff `apply_patch` | Repair an existing function while preserving a neighboring user edit; reject an obsolete replacement target. |
| C05 | Run commands and inspect exit status/output | `agent/tools/code.py`: `terminal`, `execute_code`; package environment tools | Present | Run the documented test command in the selected project, report its actual exit status, and cancel an owned slow command. |
| C06 | Resume a long-running terminal and send input | `agent/tools/background.py`, `agent/background/processes.py` | Partial; detached Python jobs exist, but these are not equivalent to an interactive PTY with stdin | Start a command, return a handle, read incremental output, send input, cancel, and reap only the owned process group. |
| C07 | Execute data analysis, calculations, charts | `agent/tools/time_and_math.py`, `agent/tools/code.py`, file and document skills | Present; dependencies and artifact display unqualified | Analyze a synthetic CSV, verify totals with code, generate a chart, and open the resulting artifact in the client. |
| C08 | Search the web and retrieve source pages | `agent/tools/web.py`: `web_search`, `web_extract`, backend fallback | Present; availability and source fidelity unqualified | Find primary sources, fetch the pages, preserve URLs, distinguish dated facts from inference, and surface a failed backend. |
| C09 | Weather, market/sports data, image search and other specialized lookups | `get_weather` exists; general web/MCP/skills can supply other sources | Partial; dedicated equivalents for every lookup were not established | Verify each enabled feed returns its source, observation time, and requested subject; do not substitute stale general knowledge. Optional feeds need not block the UI release. |
| C10 | Inspect and control a browser | `agent/tools/browser.py`, `agent/skills/macos_computer_v1/engines/browser_engine.py` | Partial; current snapshot is interactive controls, not rendered page content or an image | Read the actual conversation, target a fresh control, interact, and verify the resulting page; cover stale targets and a closed session. |
| C11 | Inspect and control native applications | `agent/skills/macos_computer_v1/engines/ax_engine.py`, `_ax_lowlevel.py`, AppleScript engine, computer-use primitives | Partial; native primitives exist; action coverage needs qualification | Discover the test app, read its UI tree, enter multiline text without accidental submission, press Send, and verify exactly one delivered message. |
| C12 | Inspect screenshots and other images in context | `agent/tools/vision.py`, computer-use screenshot primitive, provider adapters | Partial; local image analysis exists; typed image transport through the core agent loop is not established | Pass a fresh screenshot into the selected vision-capable model; identify a randomized visual feature whose answer is absent from filenames and accompanying text. |
| C13 | Generate and edit images | `agent/tools/vision.py`: local generation; `jaeger_ai/plugins/ai_gen/`: cloud generation | Partial; generation exists; reference-image editing parity was not established | Generate an artifact, reopen it, then perform a requested edit while preserving specified features of the input image. Treat editing as unqualified until implemented/tested. |
| C14 | Read/create/edit PDF, DOCX, spreadsheet, presentation artifacts | `agent/skills/productivity/{pdf,docx,excel-author,powerpoint}/`; WebUI `api/office_documents.py` | Present as skills/scripts and preview code; end-to-end artifact quality unqualified | For each supported format, produce a fixture, reopen it with an independent reader, check content/formulas, render it, and inspect layout. |
| C15 | Work with a connected live document session | This assistant has document-session connector tools; Jaeger has file workflows and MCP/client integration | Unestablished for a like-for-like live session | Identify a deliberately connected document, edit a named section, preserve unrelated content, and read back the result. File editing is not live-session parity. |
| C16 | Discover connectors and invoke remote tools/resources | `jaeger_ai/core/mcp/service.py`, `jaeger_ai/plugins/mcp/client.py`, `agent/tools/plugins.py` | Partial; MCP tool discovery/calls exist; complete resource/template parity not established | Connect an owned fixture MCP server, list/call its tool, read a resource where supported, and distinguish configured, connected, and failed states. |
| C17 | Inspect GitHub repositories, issues, PRs and CI | Terminal/GitHub skills/MCP are candidate equivalents | Partial; `jaeger_ai/plugins/catalog/my-github.yaml` advertises repository UI with no provided tools, not a full GitHub connector | Read a known test PR and its failed check; perform an explicitly authorized test-repository mutation and read it back. Local Git alone does not prove remote API coverage. |
| C18 | Create web artifacts and publish through a hosting connector | File/code tools can build artifacts; no equivalent to this session's Sites hosting connector was established | Partial | Serve and inspect a local artifact; separately qualify a chosen deployment adapter, authenticated access, returned URL, and deployed content. Hosting is optional for first release. |
| C19 | Ask structured questions during ongoing work | `agent/tools/clarify_tool.py`, `clarify_gateway.py`, runtime clarification sink | Present; cross-client pause/resume behavior unqualified | Ask a multiple-choice/free-text question in Web and Swift; route the answer to the correct run and cancel without leaving an orphan prompt. |
| C20 | Report progress, receive steering, stop work | Gateway SSE/cancellation, `agent/loop/jaeger_agent.py` steering, `core/runtime/gateway_runtime.py` | Partial across clients; prior owner cancellation tests are narrower evidence | While tools run, display progress, accept a correction in the supported transport, and cancel only that request with one terminal result. |
| C21 | Delegate bounded work and collect results | `agent/tools/call_agent.py`, `jaeger_ai/main.py` delegation, `agent/delegates/{claude,codex,gemini}/` | Present; not all asynchronous modes supported; CLI adapters require installed/authenticated runtimes | Delegate a fixture task, return a durable child result, account for timeout/cancel, and keep parent identity and ownership. External delegation currently rejects background mode in `main.py`. |
| C22 | Learn/use reusable operating procedures | Bundled skills, `use_skill`/discovery, `agent/tools/skills.py`, skill revision tooling | Present; discovery is not execution proof | Load an existing skill, execute its procedure with real tools, save evidence and a reusable regression, and successfully replay it. |
| C23 | Keep task state and resume work after interruption | Gateway run/session stores, autonomous runner, context guard/compression, missions | Partial for whole multi-step tasks; substantial owner lifecycle code exists | Restart an isolated owner during a bounded task; recover its status and evidence without repeating an already completed external effect. |
| C24 | Account for time, waits and usage | `get_time`, background completion events, `agent/loop/turn_budget.py`, cost-tracking feature | Present; full accounting across all providers/delegates unqualified | Set a small test budget, trigger its boundary, pause cleanly, and show total usage including delegated work. Wait on events rather than expensive model polling. |
| C25 | Diagnose and repair an app through observed UI behavior | QA skill + browser/desktop tools + coding tools + Gateway durable work | Partial; connected self-maintenance journey remains to be demonstrated | Reproduce a failure, retain before evidence, fix its producer, run regression tests, replay the original UI journey, retain after evidence. |

## Jaeger-specific abilities to preserve beyond this session's baseline

This assistant's current tool access does not establish an always-on personal
daemon, continuous microphone/camera access, or autonomous outreach when the
session is inactive. These are Jaeger product goals, not capabilities to infer
from this session's model name.

| ID | Intended ability | Existing pieces | Qualification still needed |
| --- | --- | --- | --- |
| J01 | Durable identity and personal memory | Instance configuration; `agent/tools/identity_tools.py`, memory/persona/insight tools; entity state | Remember a synthetic preference across restart and model change; correct it; avoid stale facts controlling current instructions. |
| J02 | Notice relevant changes without a user message | Entity sensors/salience; background producers; heartbeat | Inspection still finds the `register_cognition_handler` definition but no production registration caller. Prove a relevant observation admits work; irrelevant observations stay quiet. |
| J03 | Take initiative on a standing responsibility | Schedules, missions/commitments, idle supervisor | Complete one agreed responsibility without a new chat prompt, explaining the observation and decision; enforce the existing task budget. |
| J04 | Reach the operator and receive a reply | `agent/tools/notify.py`, messaging/email tools, channels, background delivery | Deliver a real permitted notification with chat closed, show the associated task, and resume that task on reply. An AppleScript exit code alone does not prove a visible notification. |
| J05 | Voice interaction | Voice feature; `agent/tools/listen.py`, `speak.py`; Swift voice components | Microphone to transcript to Gateway answer to speech, plus interruption and a visible error on unavailable input/output. This session's audio-output helpers are not proof of live microphone access. |
| J06 | Shared Web, Mac, terminal and other bodies | Gateway, bridge, Web proxy, Swift/TUI clients | Five actual composer turns, shared history, streaming, cancel, attachments, approvals, reconnect; native Mac test must launch and control the real app. |
| J07 | Improve skills and eventually its own implementation | Skill notes/revisions, capability registry, tools and tests | Produce a tested candidate outside live state, retain reproducible evidence, activate only within granted scope, and recover the prior working version. |

## Concrete producer gaps found during inspection

1. **Observations:** `tools/browser.py::_snapshot` enumerates visible interactive
   controls (maximum 60), not complete page text. The browser engine maps
   `screenshot_page` to `snapshot`. Add actual screenshot capture and rendered
   content/error observations without breaking existing action names.
2. **Native action contracts:** `vision_engine.py` calls module-level
   `computer_click`/`computer_screenshot` wrappers that are local definitions
   inside `computer_use_v1/computer_use.py::register`. Also, `AXEngine.can_handle`
   claims `read_ax_tree`, but its inspected `execute` method has no matching
   branch. Test every advertised action against its actual executor, not only
   the planner with fake engines. Preserve existing permission checks when
   correcting dispatch.
3. **Images reaching the brain:** `schemas/message_types.py::Message.content`
   is typed `str | None`. The inspected Anthropic adapter coerces tool content
   to text and does not declare vision support. A separate local `vision_analyze`
   call is useful, but does not establish native screenshot reasoning in the
   selected conversational model. Introduce/qualify typed content blocks and
   artifact references through tool results, adapters, storage, and replay.
   Text-only models should use an explicit vision delegate or report the limitation.
4. **Interactive execution:** `terminal` returns a completed command result;
   detached background processes use `stdin=DEVNULL`. Reuse existing process
   ownership to add resumable output/input when required; do not mistake detached
   execution for an interactive terminal.
5. **Verification truth:** `core/capabilities/registry.py::verify` returns success
   when no verifier is supplied. That is not independent outcome evidence. At the
   qualification/reporting boundary, distinguish execution success, unverified
   outcome, and observed success. A report file alone cannot qualify UI repair.

These findings describe the inspected working tree. Another agent is implementing
related changes; recheck each before editing and avoid overlapping ownership.

## Implementation order and effort

Effort is relative scope, not a calendar estimate. This ordering prioritizes the
working WebUI/Mac experience and reliable self-maintenance over breadth.

| Phase | Work | Impact / risk / effort (1–5) | Why now |
| --- | --- | --- | --- |
| P0 | Fix real composer routing and prove Web/Mac conversation journeys, C20/J06 | 5 / 5 / 3 | The operator must be able to use the product. |
| P1 | Correct browser/AX/vision contracts and qualify C10–C12 | 5 / 4 / 3 | Gives the assistant accurate observations and usable controls. |
| P2 | Connect C25 repair workflow; preserve failure evidence and deterministic replays | 5 / 4 / 3 | Converts discovered bugs into repairs and inexpensive regression coverage. |
| P3 | Qualify process resume, delegation, task recovery, and budgets, C06/C21/C23/C24 | 4 / 3 / 3 | Makes longer jobs practical without repeated prompting or uncontrolled retries. |
| P4 | Complete one proactive responsibility, J01–J04, and voice/client feedback | 5 / 3 / 3 | Demonstrates the personal-assistant goal beyond reactive chat. |
| P5 | Qualify remaining document, creative, connector and hosting capabilities | 3 / 2 / 4 | Preserve them; qualify according to actual operator use instead of blocking first release. |

Use the existing tool/capability metadata to expose a compact capabilities view
in Web and Mac: **installed**, **available now**, **blocked with reason**, and
**last successful check with evidence**. Do not introduce a competing catalog or
turn sample UI cards into claims of working capabilities. Absence of credentials
or OS permission must be reported separately from an implementation defect.

## What makes an equivalent suitable

For each row, record its owner, registered tool/skill, model requirements,
availability probe, acceptance task, last result, and evidence path. Qualify via:

1. A deterministic component contract (including negative/error cases).
2. A Gateway-owned invocation with isolated state and a known expected result.
3. The relevant actual UI journey when the capability is user-facing.
4. A small configured-model check for model-dependent behavior; scripted answers
   establish transport, not autonomous judgment or vision competence.

Use inexpensive tests for routine replay. Use model reasoning and screenshots
for exploration or ambiguous failures. Keep work, evidence, builds and runtime
state outside the repository. Do not change live deployment or account access
merely to fill this matrix. Do not auto-install optional providers or download
model weights during the audit.

## Verification performed in this audit

Source inspection and one focused run; no live browser/desktop exercise, paid
model call, connector authentication, or deployment performed:

```sh
dev/scripts/run_tests.sh --unit \
  dev/tests/jaeger_ai/skills/test_macos_computer_planner.py \
  dev/tests/jaeger_ai/skills/test_macos_computer_goal_parser.py \
  dev/tests/jaeger_ai/core/test_capabilities_layer.py \
  dev/tests/jaeger_ai/core/test_model_router.py \
  dev/tests/jaeger_ai/core/mcp/test_service.py \
  dev/tests/jaeger_ai/features/test_clarify_wire.py --tb=short
```

Result: **54 passed in 5.26 seconds; exit 0**. These tests cover bounded planning,
configuration, routing and component contracts, including fake engine behavior.
They do not establish actual browser/AX execution, image transport, authenticated
connectors, or complete client acceptance. The only authored change in this
audit is this document; no production fixes or complete parity are claimed.

Scope excludes platform-specific account administration and emergency-resource
tools that happen to be exposed to this session but are not Jaeger product
requirements. Connected-tool availability in the assistant also does not prove
every connected account action succeeds. No claim is made about OpenAI's private
architecture, training, memory infrastructure, or hidden reasoning mechanisms.
