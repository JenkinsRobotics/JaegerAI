# Complete approval action visibility, 2026-11-08

## Defect and correction

The prior gateway approval target selected a fixed subset of argument names and
clipped each value at 200 characters. Two commands with identical long prefixes
and different consequential suffixes displayed identically. Working directory,
environment and timeout arguments could be absent. The UI labeled that summary
as an exact command. A retained synthetic before-control reproduces the issue
without executing those commands. This is a source defect, not a claim that the
current dirty runtime installation was tested or changed.

The producer now displays every supplied permission-request argument as a
JSON-valued pair without clipping. Ordinary ASCII identifier labels remain
plain; other labels and all non-ASCII/control values use explicit JSON escapes.
This prevents MCP extra-argument keys from forging lines and Unicode directional
formatting from disguising displayed commands or paths. False and empty values remain visible. Known
credential labels and recognized text forms are masked in a display-only copy;
execution arguments are not changed. Raw strings are sanitized before JSON
escaping and the rendered pairs are sanitized again. Ordinary author, recipient,
working-directory and token-count data remain visible. The canonical shared
redactor and approval/grant policy are unchanged.

Only exact builtin JSON-compatible values are displayed. Unsupported values,
unsupported mapping keys, cyclic objects and nonfinite numbers have explicit
unavailable markers. No supplied custom object conversion or container method
is called. A mapping with an unsupported key is marked unavailable as a whole,
rather than silently dropping that key.

The card calls the text a requested action and explains redacted secrets, omitted
defaults, unavailable values and old summary-only requests. Its full authoritative
prompt has its own wrapped, scrollable element even when a bounded progress tool
preview is also present. The preview remains a preview, not authorization proof.

## Verification and rejected candidate

Independent review rejected the first candidate because custom `str` conversion
could expose unrelated internal object data, and the active-preview path showed
the full prompt outside the wrapped scrolling element. It also identified stale
exact-string tests and missing explicit private-key/space-separated API-key
labels. Those failed probes, the rejected source patch and corrected probes are
retained separately. They are not relabeled as passing results.

The intermediate reviewed revision was builder e03564120ef546399e2e89b8b43cb3f1da9ae38b,
tree 133fad535e528df404d8b61a91cb5e2f4439d228. Its patch SHA-256 is
11b8e8dd6e6c7c9159f645d72e4eb560ac6ee588edc2f14ec202fc521d3803ed.
Independent verification passed 95 focused/adjacent tests, three added contract
controls, one owned default-report HTTP journey, seven UI tests, TypeScript and
the repository verification pipeline. A synthetic 60,000-character backend
request and large UI prompt preserve the ending and full authoritative content.

A final adversarial review then superseded that approval. The real MCP adapter
accepts extra raw argument keys, so a newline key could appear to be a second
working-directory argument even when values were escaped. Actual directional
and nonprinting Unicode controls also survived value serialization. Retained
stubbed-adapter and display probes show both defects without external dispatch
or a browser. No authorization bypass was demonstrated.

The final corrective freeze is 5bd452d446ad2128e5ce996c33a6590098beb62c,
tree b1fd49e1d7a2aa84cfa3c018d1bded787a26da31. Its minimal delta from the
intermediate revision has SHA-256
93ada4ecd41a336b9e6e663a961204454ca5f92e082655e7874b1cf28e096a17.
Independent final review passed 104 backend/contract tests and seven UI tests,
including the actual stubbed MCP producer, nonordinary labels, nested directional
values and unchanged dispatch arguments. Execution arguments and permission
policy remain untouched. Earlier passing gates and failed controls are retained
separately. Final combined backend gates rerun this corrected source.

Concurrent waits retain distinct approval UUIDs and resolve the matching live
future. The resolver rejects a conflicting second settlement. Repeated/conflicting
clicks cannot submit twice in one frame; an unknown response does not trigger an
automatic retry, and an explicit retry retains the same approval ID. These are
existing authority mechanics exercised independently, not a new permission grant.

The integrated Research acceptance test independently decodes every displayed
JSON value, rejects duplicate keys and approval IDs, compares all supplied values
to the known scripted call, and pins paths/command/request/session identity before
one-time approval. Its first strict-map check exposed the native terminal adapter
adding timeout_s=60.0 to its permission request. That failed run was retained.
The fixture correction explicitly supplies the same supported timeout, preserving
whole-map equality rather than ignoring extra arguments. File adapter maps have
no such expansion and are checked exactly.

Final main source passed 98 approval/expiry/identity tests, 54 selected owned
HTTP/process cases (3 exclusions), and repository verification. The fresh
production UI build passed 913 tests in 201 files. Full combined gates, source
freeze and archive checks are recorded in the combined qualification report.

## Scope and remaining acceptance

This is display-only visibility of the permission request's supplied arguments.
Native adapters may already have expanded some values before that request;
remaining effective defaults are not inferred. The display is not a durable
argument fingerprint, immutable snapshot or cryptographic execution check.
Nested in-process mutation between review and execution is not newly protected.

Redaction is best effort for recognized forms/labels, not universal secret
recognition. Unlabelled/encoded credentials may remain visible. Historical rows
cannot recover already discarded details. Existing request-size limits remain;
the tested large values are not an arbitrary-size performance guarantee.

DOM tests prove content and the correct style class; CSS wraps, scrolls and caps
height. They do not prove rendered browser/phone/native visual interaction. No
real provider, runtime machine, external recipient or real credential was used.
No permission expansion, persistent grant, merge, installation or deployment
occurred. Approval functionality and every tab remain PARTIAL.
