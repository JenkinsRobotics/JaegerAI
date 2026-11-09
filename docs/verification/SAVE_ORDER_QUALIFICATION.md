# Studio save order qualification

Overall product status remains PARTIAL. The accepted increment repairs overlapping whole-snapshot saves within one mounted Board owner. It is not a runtime deployment or whole-Studio acceptance.

## Exact source

Production source f54428bfa99b0696cbfb4bb0e367f7d0ba42866e, tree fe0dd61b218ec6f247518ad4d7aa28b76ed38eb6, parent 8d6e94454a32a98b420dc99d243420f6d6bf7023. Only StudioPage.tsx and StudioBoard.test.tsx changed from that parent: 85 insertions and 6 deletions. Full-history baseline remains ff71bb769bc56e4c6d7be6d540a86be73e291e07. No history rewrite is proposed.

Saved version 17 remains unchanged: ZIP SHA256 6dccdd0cbc601b6ebb8fb763a64aa156686f685255cf435096c2876397f3976c, 65309572 bytes. It contains production 731258db703fc1c95913042395f8e9ce4fbb9b21 and documentation 8d6e944. This candidate is a local source/evidence review artifact, not a saved replacement or installer.

The latest recorded upstream observation is canonical master 3926eedd353faaf9ddd54eecf74a9f6fbd003707 at 2026-11-09 03:41:44–45 UTC. This dated observation is not a fresh latest-head claim. Remote publication remains blocked by the prior GitHub write 403; no retry, merge or deployment was performed.

## Behavior and limits

One mounted owner sends at most one PUT at a time. Later edits coalesce and dispatch after its acknowledgment. Revision and owner guards retain newer local edits and prevent stale acknowledgments from releasing a newer owner's lock. A rejected or unknown save outcome latches automatic writes off for that owner. Local edits remain visible and a persistent warning advises keeping the view open and copying notes. There is no Retry control or reload advice, and no completed-save receipt is claimed.

A new owner does not fence or cancel a previously dispatched server write. Cross-owner and multiple-client ordering, explicit safe retry/reconciliation, navigation draft recovery and backend asset atomicity remain unimplemented or unqualified. A successful response does not prove disk durability; a rejected response does not prove no mutation.

## Evidence chronology

- Original independent ordering evaluator: baseline 1 failure and 1 passing control. Preserve unchanged evaluator and failing log.
- Pre-implementation positive acceptance evaluator: baseline 1 failure and 5 passing controls. Preserve unchanged evaluator and failing log.
- Builder focused controls: 25 passed; original ordering probe: 2 passed.
- Builder initial typecheck: exit 2 because an external UI-only snapshot lacked sibling IDE timeline inputs. Corrected exact sibling inputs: typecheck exit 0. Preserve both; do not infer a product defect from the setup failure.
- Independent final review: 29 passed, exit 0. Includes both unchanged evaluators, current Board/provider-unavailable controls and two heldouts for stale-owner acknowledgment and committed-but-lost-response with later edits. React/API timing is mocked, with synthetic persisted state; this is not live HTTP concurrency, browser/native or provider acceptance.
- Fresh final production UI build: exit 0. Full UI suite: 1079 passed across 218 files, exit 0. Final aggregate verification passed: 142 Python checks and 294 IDE tests. The unchanged 29-case Studio controls, root wheel/sdist rebuild and all ten archive checks passed, exit 0. No new gate failed.

## Reused evidence and distributions

Prior 731 selected backend gates and broader b129 HTTP/durable/lifecycle gates are explicitly reused for unchanged domains, not rerun on f544. Source/domain proofs enumerate 5583 physical source entries and 1950 companion inputs. Eight companion distributions have exact reused hash proofs. Root wheel/sdist were freshly rebuilt; all 138 exact final UI files, mock=false/source fingerprint, RECORD and required runtime/source bytes passed verification in both archives. StudioPage.tsx and StudioBoard.test.tsx are explicitly required in both archives by unchanged package-data configuration. Ten archives were verified locally; their binaries are not included in this source/evidence artifact.

The package checker retains runtime, UI, mock=false, RECORD and archive assertions. It excludes exactly three source-only feature README files (agent_bridge, backlog, voice), whose lack of executable consumers was independently checked. Complete source documentation remains in Git history. Preserve the historical overbroad checker failure and its narrow correction. Original corrected checker SHA256 cbc43812177260e697942fa2ff10629ba6f6040aa5dfa9dc86676cfa226928eb; final adapted checker must carry its separate hash and adaptation proof.

## Independent review boundary

All final qualification records are included under test-evidence/save-order-final with original-to-sanitized hash mapping. Root wheel SHA256 6c613984ca2362c760c43353988c955f7547443c387ec57fed5357aeef47ca9e; root sdist SHA256 8b70bfd9f4867d61e635315a83973cbdf4067adedd8ab8526fc7f921fb8de597. The builder receipt records local archive checks; separate independent approval of the exact ZIP remains required before any saved replacement. Review must cover exact bytes, safe unique members/CRC/hash manifest, offline Git import, full ordered parents, patch/tree equivalence, every stored object including unreachable/delta bases, privacy, and package provenance. No upload has occurred.
