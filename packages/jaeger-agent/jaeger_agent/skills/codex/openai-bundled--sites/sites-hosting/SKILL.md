---
name: sites-hosting
description: Host websites with Sites. Use after `sites-building` to privately publish a Site created in this flow or for requested publishing or deployment, and for hosting management or projects containing `.openai/hosting.json`.
---

# Sites hosting

When entering an existing checkout directly, run `node <plugin-root>/scripts/configure-execution-profile.mjs --execution-profile portable` before installation, builds, or preview. Preserve custom projects; restart an existing preview if the profile changed. When continuing from `sites-building` in the same environment, reuse its selection.

Publish the exact source with the shortest safe sequence. Use native Sites connector calls directly, following their descriptions for arguments and archive requirements. Treat IDs and cursors as opaque and copy them unchanged from the selected Site's manifest or tool responses.

Read `references/environment.md` for this environment's native tool calls, archive delivery, and final handoff.

## Site lifecycle ownership

Only the Site-owning agent responsible for the user's requested Site may run `sites-hosting`, call `create_site` or any other Sites tool, edit the Site checkout or `.openai/hosting.json`, obtain source credentials, commit or push, save a version, deploy, or perform the final browser handoff. A spawned subagent must return its assigned image, asset, or research result without invoking this skill or any Sites tool. An independently started background or invisible task that owns the requested Site remains its Site-owning agent.

## Communicate clearly

Assume the user is a nontechnical knowledge worker. Keep source control, credentials, IDs, commits, branches, archives, versions, packaging, connector calls, and deployment polling out of user-facing messages. Usually send one update when publishing begins, then the final URL or a plain-language blocker.
For example: `Your site is ready. I’m publishing it privately now.`

## Rules

- After implementation, privately publish a Site created in this flow by default. Deploy existing Sites when the user requests publishing or deployment. Respect local-only requests, requests to save without deploying, and instructions not to publish.
- Honor the Site and audience in the user's request. For “publish this Site,” use its current audience unless the user specifies another. Do not add a separate conversational deployment confirmation; runtime tool approvals and backend access checks still apply.
- Publishing does not require additional browser testing or visual QA. Preserve the existing Site tab as its single user-facing view; a failed browser handoff does not block publishing.
- Treat `public/screenshot.jpeg` (`screenshot.jpeg` under `static.directory` for buildless sites) as an optional deployment thumbnail. Preserve an existing file. Create or refresh it only when the user explicitly requests a Sites deployment thumbnail; a generic screenshot request does not count. Missing or failed capture never blocks version saving or deployment.
- Store only `project_id`, optional `static` configuration, logical `d1` and `r2` bindings, and requested supported `capabilities` in `.openai/hosting.json`. Manage runtime values through Sites.

## Fast publish sequence

For unchanged source with a known archive-backed version, reuse that version instead of rebuilding, committing, packaging, uploading, or saving again; continue at step 5. A source-only version may still need its first archive; saving the matching source and archive completes that same version. If the requested version's deployment is already running, continue at step 8 instead of starting another deployment. Use known response IDs; do not add discovery calls to this path.

`<plugin-root>` is the installed plugin directory containing `skills/` and `scripts/`. Run each script directly in a separate exec call with absolute paths and literal arguments, without shell variables, redirects, or chaining. Set exec's working directory to the Site checkout and poll yielded sessions to completion.

1. Reuse output from the last successful build when the source has not changed. Plain static assets need no build; otherwise rebuild only when needed, using `node <plugin-root>/scripts/build-site.mjs`.
2. Collect the registration call started during `sites-building` before committing or packaging, then re-read `.openai/hosting.json` and verify its `project_id`. Reuse that Site and its source write credential; renew a missing or expired credential for the same Site. If hosting a new Site directly, start registration only when no `project_id` or unresolved prior attempt exists. Follow [Register once while building](../sites-building/references/environment.md#register-once-while-building) for the call, persistence, and recovery steps.
3. Use a Git repository rooted at the selected Site project, initializing one there if needed; do not commit or push an unrelated parent repository. Commit the exact source. Push it with the returned credential as a per-command HTTP authorization header. Keep the credential out of remote URLs, Git configuration, files, and user-facing output. Wait for the push to finish successfully, then run `git rev-parse --verify HEAD` in the Site checkout and copy its complete output verbatim as `commit_sha`. Never expand, pad, or guess a SHA from abbreviated commit or push output. Keep that source revision unchanged through packaging and saving.
4. Package with `node <plugin-root>/scripts/package-site.mjs <project> <archive>`.
5. For a site created in this flow whose owner-only access has not changed, or an existing site already known to be owner-private for the selected account, continue directly to step 6 without `get_site`. The private operation checks current ownership and access. For other sites, call `get_site` to resolve the current audience and use step 7 when deployment to that audience is within the user's request. Never use private deployment as an access probe.
6. For private publishing, use `deploy_private_site_version` when reusing a stored archive's version. Otherwise, use `save_version_and_deploy_private` when exposed in the current tools, passing the pushed `commit_sha` and archive. It saves and privately deploys that exact version in one call; do not save separately first. If the tool is unavailable or returns `tool_not_enabled`, use `save_site_version` followed by `deploy_private_site_version` with its returned version ID. If private hosting returns `site_not_owner_only`, do not retry private or silently fall back: call `get_site` to resolve the current audience and continue at step 7 only if the user's request covers that audience. Otherwise, report the audience mismatch.
7. Outside the private path, save one version and call `deploy_site_version` for the requested deployment. Reuse an already saved version instead of saving again.
8. If the returned deployment status is not terminal, poll `get_deployment_status` directly until it succeeds or fails. Do not poll after a terminal result. Use discovery calls only when an error requires them.

If hosting fails after saving and returns `saved_version_id`, retain it and resume with the appropriate deployment tool after addressing the failure; do not repeat the save. If a timeout or lost response leaves the outcome unknown, reconcile existing versions for the pushed commit before retrying. Leave build errors and repairs to the agent; the combined tool does not build or repair local source.

On `stale_commit_sha`, rerun `git rev-parse --verify HEAD` and verify that commit is the configured remote branch's HEAD before retrying. If the source changed, rerun any required build, commit, push, and package it again. Do not substitute a different remote SHA while keeping an archive built from another revision.

## Existing sites and advanced capabilities

- Reuse an existing `project_id` and valid source credential when available.
- If a credential is absent or expired, obtain one with `create_source_repository_write_credential` and reuse it until expiry.
- If the D1 schema changed, ensure generated migrations are present before packaging.
- For server-backed builds, require `dist/server/index.js`, static assets when emitted, `dist/.openai/hosting.json`, and `dist/.openai/drizzle/**` when migrations exist.
- For static-only builds, require an `index.html` in the public output directory selected by `static.directory` in `.openai/hosting.json`. The helper normalizes that output to `dist/` and rewrites the archived `static.directory` to `dist`. Static builds cannot use runtime bindings, capabilities, or migrations.
- For non-vinext server-backed projects, use the established Cloudflare Workers-compatible build output and adapt staging only as required by the connector contract.

## Handoff

After the deployment response or `get_deployment_status` reports `status: "succeeded"`, follow the Handoff section in `references/environment.md` to show the exact deployed URL. Preserve the existing Site view after subsequent fixes and redeployments.

Then return the deployed Sites URL and a concise description of what the user can do. If the deployment is unsuccessful, do not perform the success handoff; explain the user-visible reason and next step. Keep source credentials and temporary archives private. Do not include file paths, commands, build details, IDs, commits, or version information unless the user asks.
