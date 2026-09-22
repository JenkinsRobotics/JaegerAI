# Hermes Agent integration

Hermes Agent remains an external agent runtime. JaegerAI uses its authenticated
native Runs API through `native_adapter.py`; the first-party Jaeger WebUI is a
separate feature under `jaeger_ai/features/webui`.

The host service is launched by `scripts/hermes-native-api-service.py` from the
Hermes Agent checkout configured by `JAEGER_HERMES_AGENT_SRC` (default
`jaeger_ai/vendor/hermes_agent` inside JaegerAI). Runtime state remains in `~/.hermes` and the API binds
only to `127.0.0.1:8645`.
