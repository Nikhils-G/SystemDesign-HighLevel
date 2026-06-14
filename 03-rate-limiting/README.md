# Rate Limiting — System Design Topic 03

Topic 02 was about not paying twice for the same answer. This one is the other half: stop a single client from running up the bill at all. For an AI backend a leaked key or a runaway loop is a money leak, not just load — a rate limit is the circuit breaker.
**One question:** how do you cap how fast any one caller can hit you, and tell them politely when they've hit the wall?

---

## 1. The algorithms — at a glance

| Algorithm      | Burst behaviour   | Smoothness        | Memory / client   | Best for                              |
|----------------|-------------------|-------------------|-------------------|---------------------------------------|
| Fixed window   | high (at seams)   | poor (2× at edge) | one counter       | rough, cheap protection               |
| Sliding window | low / none        | good              | one stamp/request | strict steady caps                    |
| Token bucket   | controlled bursts | good              | two floats        | general API limiting (the default)    |
| Leaky bucket   | none              | perfect           | a queue           | shaping a constant feed downstream    |

**Short rule of thumb:**
- **Token bucket** → most APIs. Let clients burst a little, cap the sustained rate.
- **Sliding window** → when the limit must be strict with no boundary loophole.
- Always answer with **`429` + `Retry-After`** so clients back off instead of hammering.

---

## 2. What's in this folder

```
03-rate-limiting/
├── README.md       this file — the 2-minute overview
├── concept3.md     the deep "why" — algorithms, identity, distributed, AI angle (read after this)
├── limiter.py      two algorithms (token bucket + sliding window), per-client budgets
└── app.py          FastAPI app: a dependency that enforces limits and returns 429 + headers
```

**The demo in one sentence:** `POST /chat` sits behind a token bucket (burst 5, refill 1/s) and `GET /search` behind a sliding window (3 per 10s), each keyed per `X-API-Key`, so you can watch `X-RateLimit-Remaining` drain and trip a real `429 Retry-After` from `curl`.

---

## 3. Concepts we touch

- Token bucket (burst + steady refill) vs sliding window (strict, no boundary burst)
- Per-client identity: `X-API-Key` first, IP as a weak fallback — and why that matters
- The `429` contract: `Retry-After`, `X-RateLimit-Limit` / `-Remaining`
- FastAPI dependency as the enforcement point (check before the handler runs)
- Distributed limiting: why the in-memory dict breaks across instances → Redis
- The AI angle: limiting by *tokens* not requests, concurrency caps, the provider's own 429s

---

## 4. How to run

```bash
pip install fastapi uvicorn
uvicorn app:app --reload
```

Then poke at it:

- **Token-bucket burst** — fire 7 quick requests; the first 5 pass, then `429`:
  ```bash
  for i in $(seq 1 7); do \
    curl -s -o /dev/null -w "%{http_code} " \
      -X POST http://localhost:8000/chat -H "X-API-Key: alice"; \
  done; echo
  # 200 200 200 200 200 429 429   — wait a couple seconds and it recovers
  ```

- **See the headers** — watch the budget and the retry hint:
  ```bash
  curl -i -X POST http://localhost:8000/chat -H "X-API-Key: alice"
  # X-RateLimit-Limit: 5 / X-RateLimit-Remaining: N on success
  # on a 429: Retry-After: <seconds>
  ```

- **Sliding window** — 3 per 10s on a different route:
  ```bash
  for i in $(seq 1 4); do \
    curl -s -o /dev/null -w "%{http_code} " \
      http://localhost:8000/search -H "X-API-Key: alice"; \
  done; echo
  # 200 200 200 429
  ```

- **Per-client isolation** — a different key gets its own fresh budget:
  ```bash
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST http://localhost:8000/chat -H "X-API-Key: bob"
  # 200 — bob is untouched by alice burning through her bucket
  ```

→ Open `concept3.md` for the full reasoning.

---

## 5. Sources I learned from

- [MDN — `429 Too Many Requests`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/429) and [`Retry-After`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Retry-After) — the response contract
- [Cloudflare — what is rate limiting](https://www.cloudflare.com/learning/bots/what-is-rate-limiting/) — the why, in plain terms
- [Stripe — scaling your API with rate limiters](https://stripe.com/blog/rate-limiters) — token bucket in production, and layered limit types
- [Token bucket vs leaky bucket — Wikipedia](https://en.wikipedia.org/wiki/Token_bucket) — the algorithm definitions
- [Redis — rate limiting patterns](https://redis.io/glossary/rate-limiting/) — distributed counters across instances
- [Anthropic — rate limits](https://docs.anthropic.com/en/api/rate-limits) — the upstream-`429` angle: you're a client too
