# oss_stack

Phase-1 OSS stack: model router, shared MCP tool servers and Documents RAG.

- `router.py`, `routes.py`: model routing and its Gateway routes.
- `mcp_pool.py`: shared MCP tool servers.
- `docs.py`, `docs_indexer.py`: Documents RAG (the `jaeger-docs-indexer` service, Qdrant).
- `browser_proxy.py`: loopback forward proxy for the shared browser with DNS-pinned public destinations.

Touchpoints: Gateway, Research › Documents, the docs-indexer LaunchAgent.
