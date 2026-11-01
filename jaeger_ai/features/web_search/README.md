# web_search

Shared Jaeger web search for every hub caller: local SearXNG on loopback plus a safe page fetch.

- `routes.py`: `POST /v1/search` and `POST /v1/fetch` (scope `search`, loopback only); each call publishes a `search.query` / `search.fetch` activity row attributed to the caller.
- `service.py`: the SearXNG client and fetcher.

Touchpoints: Gateway, agents' search tools, the Colima SearXNG container.
