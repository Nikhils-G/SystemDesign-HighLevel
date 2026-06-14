# System Design Experiments

Focused experiments; Each folder answers one real question I had while shipping things. `NN-name/` per topic — open the folder's README for the full story.

## Done

- **01** — [REST vs GraphQL](./01-rest-vs-graphql/) · FastAPI hybrid: REST + SSE for streaming, GraphQL for the data plane
- **02** — [Caching](./02-caching/) · HTTP caching (ETag/304) vs application cache vs LLM response caching, and the invalidation trap
- **03** — [Rate limiting](./03-rate-limiting/) · token bucket vs sliding window, per-client budgets, 429 + Retry-After, and limiting by tokens

## Planned

04 Load balancing · 05 Message queues · 06 WebSockets vs SSE vs polling · 07 Observability · 08 Auth & sessions
