# Caching — System Design Topic 02

Topic 01 ended on a loose thread: GraphQL "breaks HTTP caching," but I never said what that actually costs you. This folder pays that off — one FastAPI process showing three caches at three layers, with the latency win you can see from `curl`.
**One question:** where do you cache, and what does each layer buy you?

---

## 1. The layers — at a glance

| Layer                    | Caches                          | Scope / TTL              | What it saves                          |
|--------------------------|---------------------------------|--------------------------|----------------------------------------|
| Browser                  | full responses                  | one user, per `max-age`  | the whole round trip                   |
| CDN / edge               | full responses                  | shared, per region       | long-haul latency, origin load         |
| HTTP `ETag` / `304`      | re-validation                   | any HTTP cache           | the response *body* on re-checks       |
| Application (Redis/dict) | results of expensive work       | shared, your TTL         | a DB query or an LLM call              |
| Prompt / response cache  | LLM answers by prompt           | your TTL                 | model cost + latency on repeat prompts |

**Short rule of thumb:**
- **HTTP caching (REST GET)** → free, edge-level, automatic — exactly what a GraphQL POST forfeits.
- **Application cache** → anything expensive to compute and read more than it changes.
- **Prompt/response cache** → LLM answers, where a repeated prompt should never cost a second model call.

---

## 2. What's in this folder

```
02-caching/
├── README.md       this file — the 2-minute overview
├── concept2.md     the deep "why" — layers, AI caching, invalidation (read after this)
├── cache.py        a tiny TTL cache + prompt-key normaliser
└── app.py          FastAPI app: HTTP caching + response cache + invalidation
```

**The demo in one sentence:** `GET /agents` shows free HTTP caching (`ETag` → `304`), `POST /chat` shows a cache-aside response cache collapsing a 1-second "LLM call" to ~0ms on a repeat, and `/chat/invalidate` shows why busting the cache is the hard half.

---

## 3. Concepts we touch

- HTTP caching: `Cache-Control` (`max-age`, `public`/`private`), `ETag` + `If-None-Match` → `304 Not Modified`
- Why a GraphQL POST can't use any of that (the topic-01 callback)
- Cache-aside (lazy loading) with a TTL, and lazy expiry on read
- Cache invalidation and the stale-read danger
- Eviction (LRU / LFU) — where it slots in at scale
- AI-specific caching: exact-match response caching, semantic caching, Anthropic server-side prompt caching
- Cache stampede / thundering herd

---

## 4. How to run

```bash
pip install fastapi uvicorn
uvicorn app:app --reload
```

Then poke at it:

- **HTTP caching** — grab the `ETag`, then re-request with it:
  ```bash
  curl -i http://localhost:8000/agents
  # copy the ETag value from the response, then:
  curl -i -H 'If-None-Match: "<paste-etag>"' http://localhost:8000/agents
  ```
  The second call returns `304 Not Modified` with no body — the client keeps its copy.

- **Response cache** — same prompt twice, watch `took_ms` collapse:
  ```bash
  curl -X POST http://localhost:8000/chat \
    -H "Content-Type: application/json" -d '{"prompt":"hello"}'
  # first call:  {"cached": false, "took_ms": ~1000, "answer": "..."}
  curl -X POST http://localhost:8000/chat \
    -H "Content-Type: application/json" -d '{"prompt":"hello"}'
  # second call: {"cached": true,  "took_ms": ~0,    "answer": "..."}
  ```

- **Invalidation** — bust it, then the next call is a miss again:
  ```bash
  curl -X POST http://localhost:8000/chat/invalidate \
    -H "Content-Type: application/json" -d '{"prompt":"hello"}'
  # {"busted": true} — repeat the /chat call and cached is back to false
  ```

→ Open `concept2.md` for the full reasoning.

---

## 5. Sources I learned from

- [MDN — HTTP caching](https://developer.mozilla.org/en-US/docs/Web/HTTP/Caching) — the layered model and how the headers fit together
- [MDN — `Cache-Control`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Cache-Control) — `max-age`, `public`/`private`, `no-store`
- [MDN — `ETag`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/ETag) and [conditional requests](https://developer.mozilla.org/en-US/docs/Web/HTTP/Conditional_requests) — `If-None-Match` → `304`
- [AWS — caching best practices & patterns](https://aws.amazon.com/caching/best-practices/) — cache-aside vs write-through, TTL, eviction
- [Redis — caching patterns](https://redis.io/docs/latest/develop/use/patterns/) — what the application-cache layer looks like in production
- [Anthropic — prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching) — server-side caching of the system/context prefix
- [Cache stampede — Wikipedia](https://en.wikipedia.org/wiki/Cache_stampede) — thundering herd and the single-flight fix
