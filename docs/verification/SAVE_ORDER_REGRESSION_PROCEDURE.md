# Reproducing the Studio save order regression

Use an isolated checkout of the exact candidate and an external UI snapshot with the matching sibling IDE inputs. Reuse only approved existing dependencies; put outputs, caches and synthetic state outside source. Do not use an operator HOME/database, real providers, recipients or the runtime Mac.

1. Verify commit, tree, parent and the two-file production/test delta. Record source hashes before execution.
2. Keep the original ordering and positive acceptance evaluators unchanged. Run the same probes against their recorded baseline and candidate; retain expected baseline failures rather than rewriting assertions to make old behavior pass.
3. Mount the real Board component with controlled API timing. Queue multiple edits before the first acknowledgment. Assert only one PUT is in flight and the next snapshot contains all later edits; assert persistence via the synthetic store and fresh GET, not request counts alone.
4. Distinguish pre-commit rejection from committed-but-lost-response. Queue and type newer edits after the uncertain outcome. Advance time beyond debounce and transient-toast expiry; require no automatic replay, retained local text and a persistent truthful warning.
5. Switch owner while a prior request is pending. Complete the old request and assert it cannot release the current owner's lock or mutate its UI state. Do not mistake this client ownership test for server-side fencing.
6. Run the original evaluators, current Board and provider-unavailable tests, plus independent heldouts. Keep raw machine-readable results, log, exit status and exact evaluator hashes. Run full UI/typecheck/build/aggregate checks separately on final source.
7. Check root wheel/sdist embed exact freshly built UI and preserve source, dependency and archive provenance. Reuse companion distributions only after exact input-domain/hash comparison.

The regression lesson is to enforce serialization at the save producer and clear dirty state only for the acknowledged revision. Error handling must preserve unknown outcomes, not promise that a failed request made no change. A pause latch prevents automatic replay but is not safe recovery: navigation and multi-client persistence require separate designs and evidence.

Acceptance counts overlap and must not be added as unique tests. Mock component controls, backend HTTP controls, durable restart checks, browser acceptance and native/provider acceptance are separate evidence layers.
