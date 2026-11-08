# Branch retirement — 2026-11-08

The operator authorized review, consolidation and removal of obsolete branches.
`master` remains the product source. `gh-pages` remains because GitHub Pages
is configured to publish its root. There were no open issues or pull requests
at the time of this cleanup.

Each retired branch was saved as an annotated tag under
`archive/2026-11-08/<original-branch-name>`. Remote peeled tag SHAs were verified
against the original branch tips before atomic deletion with expected-SHA leases.
No master history was rewritten. Archived WIP is not qualified release code;
archiving it does not mean every experimental feature was incorporated.

## Decisions

| Original branch | Original commit | Disposition |
| --- | --- | --- |
| `0.13-dev` | `a7a40f7e4255df07951234f00c731d362fcdf4fa` | Already merged into master. |
| `audit/hermes-suite-20261101` | `2bd2afc80cb8014e7c057c2db9d9b49b92dc238d` | All patches already present in master (cherry-picked equivalents). |
| `audit/phase-1b-auth` | `4bd830cce1ba429b3855e08ef725ca76601a054d` | Historical WIP plus control-plane fixes split into master commits; unresolved snapshot differences archived, not treated as qualified release code. |
| `consolidate/one-gateway` | `2ef73cedcc95f0016061da5b09cb07a5cc664f3e` | Historical WIP plus control-plane fixes split into master commits; unresolved snapshot differences archived, not treated as qualified release code. |
| `dependabot/pip/aiohttp-gte-3.14.5` | `45e4c6e8454259abca2f93a9d093703570c70fb2` | Closed dependency proposal; compatible pin updates already landed. Remaining minimum-version increases and major migrations are not release requirements. |
| `dependabot/pip/anthropic-gte-2.5.0` | `01877158bc0e78e28cdc25d8602ed784467bccf1` | Closed dependency proposal; compatible pin updates already landed. Remaining minimum-version increases and major migrations are not release requirements. |
| `dependabot/pip/discord-py-gte-2.7.1` | `5a5253005e919be93e2989be9eddceb405b773b6` | Closed dependency proposal; compatible pin updates already landed. Remaining minimum-version increases and major migrations are not release requirements. |
| `dependabot/pip/production-dependencies-96e48b9c2e` | `a8426a40e45c8d46125891cd7684b11d5ad59e78` | Closed dependency proposal; compatible pin updates already landed. Remaining minimum-version increases and major migrations are not release requirements. |
| `dependabot/pip/responses-gte-0.26.3` | `58b541539ff5bd723aa8ca761551da3c450edc27` | Closed dependency proposal; compatible pin updates already landed. Remaining minimum-version increases and major migrations are not release requirements. |
| `feat/mac-combined-candidate-v1` | `f829f73d5d52687a2631da38b10c6159a40378c0` | All patches already present in master (cherry-picked equivalents). |
| `feat/mcp-events` | `3153b72485bbca79545aa5eaa8265a507366286f` | Already merged into master. |
| `feat/native-stop-release-candidate` | `7422d70786cffa422c73ca4b830ab72947f15c27` | All patches already present in master (cherry-picked equivalents). |
| `fix/core-flows` | `35ef8d966a2c0a25a746717a0b80efaacaedd5a6` | Superseded by master 2a52f251 and subsequent task-owner changes; preserve original receipt-verification variant for reference. |
| `fix/j063-muse-confinement` | `6fb60960073abff4a93fe961f5640cd2d9b2ffcd` | Already merged into master. |
| `phase1b/capability-pre-autosquash` | `247594f9350eca3b9213cf2b165683afcbb1f16f` | Pre-squash/rebase snapshots. Master contains continuation, deterministic verification, tool-event arguments and stand-in ledger guards; archive the intermediate history. |
| `phase1b/capability-pre-autosquash2` | `ea43f872a2e591e9bdab748c0e6ef6d333ac09e2` | Pre-squash/rebase snapshots. Master contains continuation, deterministic verification, tool-event arguments and stand-in ledger guards; archive the intermediate history. |
| `phase1b/capability-pre-autosquash3` | `4efa46e0a3e32052e6b2033f3ecf2568379d1eba` | Pre-squash/rebase snapshots. Master contains continuation, deterministic verification, tool-event arguments and stand-in ledger guards; archive the intermediate history. |
| `phase1b/capability-pre-datefix` | `daa23404d98802845fdb2223c148cd00d9929d71` | Pre-squash/rebase snapshots. Master contains continuation, deterministic verification, tool-event arguments and stand-in ledger guards; archive the intermediate history. |
| `phase1b/land-dryrun` | `77536740be033890e049e5e45eca09ed23fa97b3` | Pre-squash/rebase snapshots. Master contains continuation, deterministic verification, tool-event arguments and stand-in ledger guards; archive the intermediate history. |
| `pinocchio` | `4124422b15e7f0ca28941774992000b24a151719` | Already merged into master. |
| `preserved/20261019/jaeger-ide-fix` | `da172b0b73ef061470faa01ad7dec9ffaf8bfb38` | Historical IDE snapshot; master integrated native controls and IDE repairs in d921b779 and later changes. Preserve remaining snapshot differences without merging them blindly. |
| `preserved/20261019/mac-combined-candidate-source` | `f829f73d5d52687a2631da38b10c6159a40378c0` | All patches already present in master (cherry-picked equivalents). |
| `preserved/20261019/mcp-events` | `3153b72485bbca79545aa5eaa8265a507366286f` | Already merged into master. |
| `preserved/20261019/mcpev-wt` | `3153b72485bbca79545aa5eaa8265a507366286f` | Already merged into master. |
| `preserved/20261019/stop-only-candidate-source` | `7422d70786cffa422c73ca4b830ab72947f15c27` | All patches already present in master (cherry-picked equivalents). |
| `release/0.14.0` | `c12aebc85580fd35fc56e9eaedc384f3ba706391` | Old qualification candidate, 798+ commits behind master. Includes annotation route later explicitly reverted (6b87cb67); do not merge or publish this candidate. |
| `ui/codex-style-shell` | `02860ff3d9b0c0d189d1553dd026c0fa158ae0d4` | Already merged into master. |
| `wip/blueprint-20261021` | `218c2ff5292f92469a4a107b960136ffeec19681` | Unfinished alternative phone/theme work; archive rather than replace the current canonical UI or approved avatar. Any reuse requires a separate tested change. |
| `wip/design-tokens-20261021` | `fc9f4695cd7ac905237cf128566fcf3996b34cbf` | Unfinished alternative phone/theme work; archive rather than replace the current canonical UI or approved avatar. Any reuse requires a separate tested change. |

## Recovery

Inspect an archive without changing the current checkout:

```sh
git fetch origin --tags
git show archive/2026-11-08/release/0.14.0
```

Restore a branch only when its work is needed:

```sh
git branch recovered-release archive/2026-11-08/release/0.14.0
```

Do not merge archived snapshots wholesale. Compare the specific change with
current master, check for subsequent fixes/reverts, and test before landing it.

## Release gate

A clean branch list is not release qualification. Before publishing a new version:

1. All required CI and browser feature workflows pass on the same master commit.
2. Preserve/reconcile any local Mac Studio source changes before deployment.
3. Run `scripts/deploy-live-mac-studio.sh`; require matching source, installed,
   public UI hashes and healthy services at the expected commit.
4. Verify live sessions/history across clients, approvals, queue/steer, model
   selection, and responsive Chrome/Safari behavior.
5. Align package/version surfaces and release notes; publish a matching immutable
   version tag only after those checks pass. Never move existing release tags.

The old `release/0.14.0` snapshot is not the next release source. In particular,
its handoff annotation route was subsequently reverted on master in `6b87cb67`.
The remaining alternate phone/theme and unreviewed snapshot differences are
archived development material, not implied requirements for this release.
