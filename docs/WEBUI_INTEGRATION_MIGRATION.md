# WebUI integration migration

> **Superseded 2026-09-16.** The migration described below used a separate
> Hermes WebUI deployment. Jaeger WebUI is now first-party source under
> `jaeger_ai/features/webui`; see [ADR-0013](architecture/adr/0013-absorb-hermes-webui.md).

## Intended topology

```text
browser / PWA
    │ authenticated same-origin HTTP + SSE
    ▼
WebUI edge :8790
    ├── stock Hermes WebUI :8787
    └── Jaeger Gateway :8810
            └── native profile Runs APIs, including Hermes :8645
```

Port 8810 remains loopback-only. The edge must authenticate the user, preserve SSE framing,
forward resume cursors, and add any backend credential server-side. Do not expose Gateway
credentials to browser JavaScript.

## Ordered rollout

1. Publish the pinned Hermes commit to a durable fork and update the submodule URL/ref only
   after a clean clone can fetch it.
2. Run `scripts/prepare-hermes-webui.py`. Record the staged path and verify its patch checks,
   stamped `api/_version.py`, extension manifest, and sidecar supervisor.
3. Build a candidate image under a new immutable tag. Keep the running 8787 container.
4. Start the candidate on unused ports and run the contract suite against its real WebUI and
   Runs endpoints. Require semantic `/version` responses and a two-turn memory check.
5. Configure the authenticated 8790 edge route. Confirm streaming headers are unbuffered and
   that unauthorized direct access is rejected.
6. Exercise one browser and two simultaneous PWA tabs. For every accepted chat POST, verify a
   corresponding stream GET begins without reload and reaches one terminal event.
7. Switch 8790 to the candidate only after all checks pass. Preserve the previous image and
   route as the rollback target.
8. Observe stream starts, sidecar health, terminal native receipts, and ownership releases.
   Roll back the edge route if any turn requires refresh or reports unknown execution.

## Patch retirement

The transition assembler has four behavior patches: `upstream.patch`, `update-labels.patch`,
`native-cancel-status.patch`, and `conversation.patch`, plus the explicit
`dispatcher-sidecar.patch` lifecycle hook. Fold each reviewed change into the published fork,
delete its patch in the same parent-repository change, and make the assembler reject any
unexpected overlay. The end state is one fetchable fork pin plus copied Jaeger extension and
adapter modules.

## Rollback

Route 8790 back to the previous healthy image. Do not rewrite session databases. The browser
continuity extension and native adapter add no schema migration, so stored sessions remain
readable by the prior deployment.
