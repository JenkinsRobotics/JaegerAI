# Actionability Classifier Validation Matrix

Evaluated against `jaeger_ai.core.runtime.autonomous_runner.is_actionable_request` on 2026-09-15. `C` means conversational/lightweight; `A` means actionable/controller eligible. The corpus deliberately includes discussion, negation, delegation, verification, quoted commands, and mixed requests.

| # | Expected | Utterance |
|---:|:---:|---|
| 1 | C | What is the capital of Egypt? |
| 2 | C | Explain this function. |
| 3 | C | What does Ollama do? |
| 4 | C | Compare Hermes and OpenClaw. |
| 5 | C | Summarize this document. |
| 6 | C | Why did this test fail? |
| 7 | C | How would you design this? |
| 8 | C | Give me an example configuration. |
| 9 | C | What is a WorkLedger? |
| 10 | C | Explain the Gateway flow. |
| 11 | A | Create foo.txt. |
| 12 | A | Modify config.py. |
| 13 | A | Fix the failing tests. |
| 14 | A | Run pytest. |
| 15 | A | Delete the temporary fixture. |
| 16 | A | Rename this file. |
| 17 | A | Update the repository. |
| 18 | A | Install this package. |
| 19 | A | Commit these changes. |
| 20 | A | Build the desktop app. |
| 21 | A | Execute the deployment workflow. |
| 22 | A | Write the requested implementation. |
| 23 | A | Check whether the build passes. |
| 24 | A | Verify this file exists. |
| 25 | A | Run the test suite without changing anything. |
| 26 | A | Confirm that port 8810 is listening. |
| 27 | A | Create the artifact and verify it exists. |
| 28 | A | Run the build and fix it until it succeeds. |
| 29 | A | Inspect the repository and record the result. |
| 30 | A | Configure the selected provider. |
| 31 | C | Explain how to delete foo.txt. |
| 32 | C | What would happen if I ran pytest? |
| 33 | C | Show me how to fix the failing tests. |
| 34 | C | Write a prompt that tells Codex to modify a repository. |
| 35 | C | Compare ways to install this package. |
| 36 | C | Should I delete this file? |
| 37 | C | What command would rename this directory? |
| 38 | C | How do I run the build? |
| 39 | C | Tell me why configuration changes are risky. |
| 40 | C | Which tool would you use to inspect this? |
| 41 | C | Do not modify any files. |
| 42 | C | Don't run tests; just explain them. |
| 43 | C | Do not use tools. |
| 44 | C | Don't execute anything; just answer. |
| 45 | C | I am not asking you to change the repository. |
| 46 | C | Text only: explain the architecture. |
| 47 | C | Reply exactly hello; do not use tools. |
| 48 | C | Do not create the file; tell me what it would contain. |
| 49 | C | Don't commit anything. |
| 50 | C | I only want a suggestion, not a change. |
| 51 | A | Explain the bug, then fix it. |
| 52 | A | Review the implementation and update it if necessary. |
| 53 | A | Tell me what's wrong and run the tests. |
| 54 | A | Compare the options and then install the best one. |
| 55 | A | Inspect this repository and report back; then make the requested fix. |
| 56 | A | Check the build and repair any failure. |
| 57 | A | Describe the issue, then modify the affected file. |
| 58 | A | Explain the change and commit it. |
| 59 | A | Review the logs and restart the service if needed. |
| 60 | A | Tell me what changed and verify the tests pass. |
| 61 | A | Have Codex fix this. |
| 62 | A | Ask Hermes to run the tests. |
| 63 | A | Let OpenClaw inspect the project. |
| 64 | A | Use Codex to modify this repo. |
| 65 | A | Delegate this coding task to Hermes. |
| 66 | A | Have Claude implement the fix. |
| 67 | A | Ask Gemini to update the configuration. |
| 68 | A | Use Grok to inspect the files. |
| 69 | A | Let Cursor run the test suite. |
| 70 | A | Delegate the build verification. |
| 71 | C | Which agent would you use to fix this? |
| 72 | C | Explain how Hermes would fix this. |
| 73 | C | What is Codex good at? |
| 74 | C | Compare delegating to Hermes versus OpenClaw. |
| 75 | C | Write a prompt for an agent to run pytest. |
| 76 | C | Should I ask Codex to change this? |
| 77 | C | How would OpenClaw inspect the project? |
| 78 | C | Tell me whether delegation is safe. |
| 79 | C | Describe the Hermes adapter contract. |
| 80 | C | Why might a delegate report success incorrectly? |
| 81 | A | Verify the calculator result. |
| 82 | A | Check whether calculator.py exists. |
| 83 | A | Confirm the tests pass. |
| 84 | A | Inspect the git diff. |
| 85 | A | Check that the artifact was produced. |
| 86 | A | Verify the service is listening. |
| 87 | A | Run swift test without modifying source. |
| 88 | A | Confirm the migration completed. |
| 89 | A | Check the generated JSON is valid. |
| 90 | A | Verify every requested file is present. |
| 91 | C | `pytest` is the command I might run later. |
| 92 | C | The docs say “create foo.txt”; summarize that section. |
| 93 | C | In a code block, show `rm -rf` usage. |
| 94 | C | What does “fix the tests” mean here? |
| 95 | C | I read that Codex can edit files. |
| 96 | C | Please explain this quoted command: “run pytest”. |
| 97 | C | Do not run `pytest`; explain the failure. |
| 98 | C | No changes, just a code review. |
| 99 | C | I meant “update” as a documentation example. |
| 100 | C | What would a completed task look like? |

## Results

The original Phase 3 classifier failed this corpus in both directions. The corrected seam produces no false positives for the pure-information, discussion, negation, delegation-discussion, or quoted-command rows and recognizes direct action, mixed action, delegation, and verify-only rows. The ambiguous “inspect and report” family is treated as actionable when it requests an external state observation; it remains read-only and still receives controller/ledger completion semantics.

The matrix is validation evidence, not a production keyword expansion plan. Structured ingress metadata remains preferable when a client already knows whether a request is text-only or action-capable.
