# ADR-0013: Absorb Hermes WebUI into the JaegerAI WebUI feature

**Status:** Accepted
**Date:** 2026-09-16

## Context

JaegerAI shipped its browser interface from a `vendor/hermes-webui` Git
submodule while keeping lifecycle, profile routing, session unification, and a
runner adapter under `jaeger_ai/features/webui`. A second container overlay
carried additional API modules and patches. The three locations described one
user-facing feature, created duplicate sources of truth, and made a JaegerAI
checkout depend on separately published submodule commits.

The browser interface will diverge further as it adopts the native macOS app's
interaction and visual language. JaegerAI also needs a single repository that
can be cloned, installed, tested, and released without coordinating another
repository.

## Decision

JaegerAI owns one first-party WebUI feature under `jaeger_ai/features/webui`:

- `server.py` and `api/` own the HTTP application and browser API.
- `static/` owns the browser client.
- `adapter/` bridges browser turns into Jaeger's native runtime.
- `service/` owns lifecycle, profile layout, and session synchronization.

The production patches and API modules formerly applied by
`integrations/hermes_webui` are folded into this feature. The Hermes WebUI
license remains beside the derived source as `HERMES_WEBUI_LICENSE` and its
lineage remains documented. JaegerAI no longer uses a Hermes WebUI submodule.

Hermes Agent remains a separate agent runtime integration. Absorbing the
browser interface does not absorb or rename Hermes Agent.

## Options considered

### Keep the Hermes WebUI fork as a submodule

This preserves a simple upstream Git relationship, but requires coordinated
publishing and leaves JaegerAI releases dependent on a second repository.

### Copy the fork under `vendor/`

This removes submodule availability failures but still presents the browser as
third-party infrastructure even though JaegerAI expects to change it
substantially.

### Absorb it as a first-party feature

This makes one repository and one feature authoritative. Upstream changes must
be reviewed and ported intentionally, but that cost matches the planned UI
divergence and removes competing implementation locations.

## Consequences

- A fresh JaegerAI clone contains the complete browser interface.
- WebUI changes and the Jaeger runtime commit atomically on `master`.
- The old submodule and container overlay are retired.
- Upstream Hermes WebUI updates become explicit source-porting work.
- The first-party feature retains third-party copyright and license notices.
- The host WebUI on port 8790 becomes the only supported browser surface.
