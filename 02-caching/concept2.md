# Caching — the deep "why"

Topic 01 ended on a complaint. In the REST-vs-GraphQL comparison I wrote that GraphQL "breaks HTTP caching" because everything POSTs to a single endpoint, and then I moved on without explaining what I was actually giving up. This is the folder where I pay that debt. By the end of it the sentence "REST gets caching for free" should mean something concrete instead of being a slogan.

---

## 1. The one bet every cache makes

A cache is not a feature you add. It is a *bet* you place, and the bet is always the same: **reads vastly outnumber writes, and a little staleness is survivable.** Every caching decision is downstream of those two clauses.

If reads don't outnumber writes — if every request asks something nobody has asked before — your hit rate is near zero and the cache is pure overhead: extra memory, extra code, extra ways to be wrong. If staleness is *not* survivable — a bank balance, an inventory count at the moment of checkout — then caching is actively dangerous and you should not do it without a hard invalidation story.

So before any of the mechanics below, the real question is: for *this* piece of data, is it read far more than it changes, and can I tolerate serving a slightly-old copy? For an AI chat backend the answer splits cleanly. Agent configs and model lists: read constantly, change almost never — cache aggressively. The answer to a brand-new user prompt: never been asked, might never be asked again — caching it only helps if prompts actually repeat. Knowing *which* of your data is which is most of the skill.

---

## 2. The layer cake

"Add a cache" hides the fact that there are at least five places a response can be cached on its way to a user, and each one saves something different.

```
browser  →  CDN  →  reverse proxy  →  application cache (Redis)  →  DB query cache
(per user)  (edge)   (per region)        (shared, hot data)         (per query)
```

- **Browser cache** — lives on one user's machine. Saves the round trip entirely; the fastest request is the one that never leaves the laptop. Controlled by HTTP headers (section 3).
- **CDN / edge** — a shared cache near the user geographically. Saves long-haul latency and shields your origin from repeated identical requests. Also driven by HTTP headers, which is *why* the headers matter so much: they are the only language you have to talk to caches you don't own.
- **Reverse proxy** (nginx, Varnish) — sits in front of your app, often per-region. Same idea, closer to you.
- **Application cache** (Redis, Memcached, or the in-process dict in `cache.py`) — this is the one you write code against. Stores the *results of expensive work* — a DB query, an LLM call — keyed by something you choose. This is where cache-aside (section 4) lives.
- **DB query cache** — the database remembering its own recent answers. Mostly automatic, least under your control.

The lesson of the cake: the higher up you cache (closer to the browser), the more you save, but the less control you have over invalidation. A browser holding a stale copy is unreachable — you cannot call it and say "drop that". So the layers trade *reach* for *power*: cheap-and-far at the top, controllable-and-close at the bottom.

---

## 3. HTTP caching — the layer GraphQL forfeits

This is the section topic 01 owed you. HTTP has a caching protocol built into it, and it costs you nothing but a couple of response headers.

**`Cache-Control`** is the instruction you hand to every cache between you and the user:
- `max-age=60` — "this is good for 60 seconds, don't even ask me again until then."
- `public` — "any shared cache (CDN, proxy) may store this," vs `private` — "only the user's own browser, never a shared cache" (use this for anything user-specific).
- `no-store` — "never cache this at all" (the bank balance).

**`ETag` + `If-None-Match`** handle what happens *after* `max-age` expires. Instead of re-sending the whole body, the server sends a short fingerprint of the response in an `ETag` header. When the cache re-checks, it echoes that fingerprint back in `If-None-Match`. If it still matches, the server replies `304 Not Modified` — a header-only response with no body. The client reuses the copy it already had. You just revalidated a megabyte of JSON by sending a few dozen bytes. (`Last-Modified` / `If-Modified-Since` is the same dance keyed on a timestamp instead of a hash.)

In `app.py`, `GET /agents` does exactly this: it fingerprints the agent list, sends the `ETag`, and returns `304` when the client already has the current version.

**Now the GraphQL problem, concretely.** All of the above keys off two things: the HTTP *method* and the *URL*. `GET /agents` is cacheable because GET is defined as safe and idempotent, and the URL uniquely names the resource. GraphQL sends everything as `POST /graphql`, with the actual query buried in the request *body*. POST is, by spec, not cacheable — it is assumed to change server state. And even if you forced it, every query hits the same URL, so the URL no longer identifies anything. The HTTP caching machinery has nothing to key on and switches off. That is the whole trade: GraphQL's flexible single endpoint is bought by giving up the free, automatic, edge-level caching that a boring REST GET gets for nothing. (The GraphQL world claws some of it back with "persisted queries" — registering queries ahead of time and referencing them by ID in a GET — but that is extra machinery to re-earn what REST had by default.)

---

## 4. Application caching — the patterns

Below the HTTP layer is the cache you actually write code against, and there are three patterns for keeping it in sync with the source of truth.

- **Cache-aside (lazy loading)** — the app checks the cache; on a miss it loads from the source, stores the result, and returns it. This is what `POST /chat` does, and it is the default for a reason: the cache only ever fills with data someone actually asked for, and if the cache disappears the app still works (just slower). The downside is the first request for any key always pays full price (the "cold" miss).
- **Write-through** — every write goes to the cache *and* the source together. Reads are always warm, but every write pays to update two places, and you cache data that may never be read.
- **Write-behind (write-back)** — write to the cache now, flush to the source asynchronously later. Fast writes, but you risk losing data if the cache dies before the flush. Specialist tool.

Then two cross-cutting concerns:

- **TTL** — how long an entry stays valid. This is your staleness budget made numeric. Short TTL = fresher but more misses; long TTL = more hits but more risk of serving old data. Set it to match how fast the underlying thing actually changes.
- **Eviction** — when memory fills, what gets thrown out. **LRU** (least-recently-used) is the common default — evict whatever hasn't been touched longest, betting that recent access predicts future access. **LFU** (least-frequently-used) keeps the popular keys regardless of recency. `cache.py` doesn't evict at all (it's an unbounded dict for the demo); a real Redis would have an eviction policy configured, and choosing it is a real decision.

---

## 5. The AI-specific layer

For an LLM backend there's a whole tier of caching that doesn't exist for a normal CRUD app, because the "expensive thing" is a model call that costs real money and a real second of latency.

- **Response caching (exact match)** — cache the model's answer keyed by the (normalised) prompt. If the same prompt comes back, serve the stored answer for free. This is what `POST /chat` plus `prompt_key` in `cache.py` implement. It is dumb and safe: a normalised string either matches or it doesn't, so you never serve the wrong answer — you just sometimes miss when you could have hit.
- **Semantic caching** — embed the prompt into a vector and match on *similarity* rather than exact text, so "what's the capital of France" and "tell me France's capital" share one cached answer. This dramatically raises the hit rate on natural-language input, where nobody phrases things identically twice. The cost is a real correctness risk: set the similarity threshold too loose and you serve a confidently-wrong answer to a question that only *looked* like the cached one. It is the right tool, but it is a tool with a blade.
- **Server-side prompt caching (Anthropic's `cache_control`)** — a different beast entirely, and worth not confusing with the above. This caches the *input prefix* — your long system prompt, tool definitions, and retrieved context — inside the model provider so that re-sending the same prefix on the next turn is billed and processed at a steep discount. You are not caching the *answer*; you are caching the *setup* that every turn of a conversation re-sends. For a chat agent with a big system prompt and tool catalog, this is often the single highest-leverage caching move, and it lives at the provider, not in your `cache.py`.
- **KV cache** — mentioned only so you don't trip over the term: this is the model's internal attention-key/value reuse during a single generation. It's the provider's concern, not an application cache, and not something you manage.

---

## 6. The two hard problems

There is an old joke that the two hardest things in computer science are cache invalidation, naming things, and off-by-one errors. The invalidation half is not a joke.

**Stale reads.** The moment you cache an answer, you have made a copy that the source of truth no longer controls. If the underlying data changes — the user edits the conversation, you swap the agent's model, a document gets updated — every cached answer derived from the old state is now a lie waiting to be served. For a chat agent this bites hard: an answer cached against one conversation context is wrong the instant that context changes.

The strategies, weakest to strongest:
- **TTL only** — let entries expire on a timer. Simple, but you knowingly serve staleness for up to one TTL. Fine when the data drifts slowly and being a-minute-old is harmless.
- **Explicit invalidation on write** — when you change the source, bust the matching cache key. This is what `/chat/invalidate` demonstrates. Correct, but only as good as your discipline: every write path has to remember to bust, and forgetting one is a silent stale-data bug.
- **Versioned keys** — embed a version number in the key (`agents:v7:...`). Changing the data bumps the version, which makes every old key instantly unreachable without having to find and delete them. Elegant when one change should invalidate a whole family of entries at once.

**Cache stampede (thundering herd).** A hot key expires. In the same millisecond, a thousand in-flight requests all check the cache, all miss, and all fire the expensive call at once — so the one moment you most needed the cache, it does nothing and you hammer your backend a thousand times. The fix is *single-flight*: the first miss takes a lock and does the work; the other 999 wait for that one result instead of each doing their own. Worth knowing the name even if the demo doesn't implement it, because it's the failure that shows up exactly when traffic is highest.

---

## 7. The honest counterpoint

Every cache you add is a second copy of the truth, and now you own the gap between the two. That gap is a new class of bug — the kind that only appears under load, only for some users, and disappears the moment you try to reproduce it. So the grown-up position is not "cache everything," it's "cache the things where the bet in section 1 clearly pays."

Don't cache when:
- **The hit rate is low.** A cache that mostly misses is slower than no cache (you pay the lookup *and* the real work) and burns memory for nothing.
- **The read must be strongly consistent.** If serving a value that's even seconds old is a correctness or safety problem, the cache is a liability, not an optimization.
- **The work is already cheap.** Caching a fast in-memory computation to "save time" can cost more in lookup and invalidation complexity than it ever saves. Measure first.

Caching is one of the highest-leverage tools in system design and one of the easiest to turn into a subtle correctness disaster. The skill isn't knowing the mechanics in sections 3 through 5 — those are just APIs. The skill is section 1: knowing, for each piece of data, whether the bet is worth making at all.
