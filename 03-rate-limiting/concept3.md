# Rate Limiting — the deep "why"

Topic 02 was about not paying twice for the same answer. This one is about the other half of the same problem: making sure a single client can't run up the bill in the first place. Caching lowers your average cost per request; rate limiting puts a ceiling on how many requests any one caller can even make. For a normal CRUD app rate limiting is mostly about protecting the server. For an AI backend it is also, very directly, about protecting your wallet — every request behind these endpoints can cost real money at the model provider.

---

## 1. Why rate limit at all

There are four reasons, and they stack:

- **Cost.** This is the one that's sharper for AI than for anything else. A leaked API key or a client stuck in a retry loop is not just "load" — it is a meter spinning at the model provider, billed to you, until someone notices. A rate limit is the circuit breaker that caps the worst case before a human is even awake to see it.
- **Abuse.** Scrapers, credential-stuffers, and people trying to drain your free tier all look like "a lot of requests from one place." A limiter is the cheapest first line against all of them.
- **Fairness.** Capacity is finite and shared. Without limits, one heavy user degrades the experience for everyone else on the same boxes. Limits keep one person from eating the whole table.
- **Stability.** Limits protect the thing *behind* you too — your database, and for an AI app the downstream model API, which has its own limits you do not want to blow through (see §6). A limiter upstream is how you stay inside the limits downstream.

The mental model: a rate limit is a *budget per unit time*, granted per caller. Everything below is about how you measure that budget and who you grant it to.

---

## 2. What you protect, and what you key on

Before picking an algorithm, answer one question: **what is "one client"?** The limiter is only as meaningful as that identity, and the choices have real trade-offs.

- **Global** — one budget for the whole service. Easy, and occasionally right (protecting a single fragile downstream), but it means one abuser can exhaust the limit and lock out everyone. Almost never what you want as the *only* limit.
- **Per API key / per user** — the gold standard. A key identifies an account regardless of which machine it connects from, so the budget follows the actual entity you're metering. This is what `client_id` in `app.py` prefers. The catch: keys leak, so a key-based limit is also a blast-radius control — if one key goes rogue, only that key's budget burns.
- **Per IP** — the fallback for unauthenticated traffic. The problem is that an IP is a blunt proxy for identity: an entire office, school, or mobile carrier can share one address (so you punish innocents together), while an attacker can rotate through many. Useful as a coarse outer wall, dangerous as your only gate.

Real systems layer these: a generous global limit as a backstop, a per-key limit as the real budget, maybe a per-IP limit on the login route specifically. The art is choosing the key that matches what you're actually trying to protect.

---

## 3. The algorithms

Four classic algorithms, each a different answer to "how do I measure a budget over time."

**Fixed window.** Count requests in the current clock window (say, per minute); reset the counter when the window rolls over. Dead simple and cheap — one integer per client. The flaw is the *boundary burst*: a client can fire its whole quota in the last second of one window and the whole quota in the first second of the next, so across that two-second seam it sustained **twice** the intended rate. Fine for rough protection, wrong when the limit needs to mean something.

**Sliding window.** Measure against a window that moves with *now* instead of snapping to clock boundaries, which closes the seam. Two flavours: the *log* version keeps a timestamp per request and counts how many fall inside the trailing window (exact, but memory grows with traffic) — this is what `SlidingWindow` in `limiter.py` does. The *counter* version approximates by blending the current and previous fixed windows by how far you are into the current one (cheaper, slightly fuzzy). You trade memory or a little accuracy for the boundary bug going away.

**Token bucket.** A bucket holds up to `capacity` tokens and refills at a steady rate; each request spends one, and an empty bucket means denial. This is the API default, and `TokenBucket` in `limiter.py` is it. Its personality is the useful one: it *allows bursts* up to the bucket size, because a full bucket can be spent all at once, but caps the *sustained* rate at the refill rate. That matches how real clients behave — a little bursty, and you only want to stop the firehose, not the occasional gulp.

**Leaky bucket.** Requests queue and drain at a fixed rate, like water through a hole. The output is perfectly smooth no matter how spiky the input — but that makes it a traffic *shaper* (it delays and evens out) more than a *limiter* (which simply allows or denies). Reach for it when the thing downstream needs a constant, predictable feed rather than just a cap.

A compact way to hold them:

| Algorithm      | Burst tolerance | Smoothness        | Memory per client | Best for                                  |
|----------------|-----------------|-------------------|-------------------|-------------------------------------------|
| Fixed window   | high (at seams) | poor (2× at edge) | one counter       | rough, cheap protection                   |
| Sliding window | low / none      | good              | one stamp/request | strict steady caps                        |
| Token bucket   | controlled      | good              | two floats        | general API limiting (the default)        |
| Leaky bucket   | none            | perfect           | a queue           | shaping a constant feed downstream        |

---

## 4. The response contract

When you deny a request, *how* you deny it matters, because a good denial lets the client recover without making things worse.

- **`429 Too Many Requests`** — the status code that says "you, specifically, are over budget" (as opposed to `503`, which says "the server itself is in trouble"). Clients and SDKs treat `429` as a signal to back off rather than to fail.
- **`Retry-After`** — the single most useful header you can send: the number of seconds until the limiter will say yes again. `app.py` computes this exactly from the algorithm's state. Without it, a client guesses, and guessing usually means an aggressive retry loop that hammers you precisely when you asked it to stop.
- **`X-RateLimit-Limit` / `-Remaining` / `-Reset`** — the running scoreboard, sent on *successful* responses too, so a well-behaved client can watch its own budget drain and self-pace before it ever hits a `429`. (These are a de-facto convention, not a standard, but they're widely understood.)

The theme: rate limiting is a two-party protocol. You're not just blocking — you're telling the client enough that it can be a good citizen on its own.

---

## 5. Distributed rate limiting

Here is the thing the demo quietly gets wrong on purpose. `Limiter` keeps its counts in a Python dict in one process's memory. The moment you scale to two instances behind a load balancer, each one keeps its *own* half-blind count, and a client whose requests spread across both effectively gets **double** its limit. At ten instances, ten times.

The fix is to move the counter out of any single process into shared state:

- **Redis `INCR` + expiry** — a fixed/sliding window counter that every instance increments against the same key. Simple and fast.
- **Redis sorted sets** — store request timestamps as scores for a true distributed sliding-window log.
- **Token bucket in a Lua script** — run the refill-and-spend logic atomically inside Redis so concurrent instances can't race on the same bucket.

And the trade-off you take on with all of them: every limit check is now a network hop. You're balancing **accuracy against latency** — a perfectly correct global count means asking Redis on every request (slower), while approximations (local counters synced periodically, or sharding clients to instances so each owns its keys) buy speed at the cost of some fuzziness at the edges. There's no free lunch; you pick where on that line you want to sit.

---

## 6. The AI-specific layer

Everything above applies to any API. A few things are specific to putting an LLM behind the limit, and they're the ones most worth internalising for this kind of backend:

- **Limit by tokens, not just requests.** One request can be a 10-token "hi" or a 100,000-token document summarisation, and they cost wildly different amounts. Counting *requests* lets a few huge prompts blow your budget while you're still well under the request limit. Mature LLM limiters meter **tokens per minute** (often alongside requests per minute) because tokens are what you actually pay for.
- **Concurrency limits.** Separate from rate is *how many generations are in flight at once*. Long streaming responses each hold a slot for seconds; capping concurrent generations protects memory and your provider quota in a way a per-minute rate doesn't.
- **Tiered limits.** Free vs paid plans get different budgets. This falls out naturally from the per-key design in §2 — the key tells you the plan, the plan picks the bucket parameters.
- **Handling the provider's *own* 429s.** You are someone else's client too. Anthropic's API has its own rate limits and will return `429`s with `retry-after` when you exceed them. So rate limiting isn't only an inbound concern — your code that calls the model must respect the downstream limit and back off on its `429`s, ideally with **exponential backoff plus jitter** so a fleet of your workers doesn't all retry on the same tick (see §7).

---

## 7. The honest counterpoint

Rate limiting is not free, and pretending otherwise hides its failure modes.

- **It adds latency and a moving part.** Every request now does a check first, and if that check lives in Redis it's a network hop on the hot path. The limiter is also a new thing that can be misconfigured or go down.
- **False positives lock out real users.** Set the limit too tight, or key on something too coarse (that shared office IP), and you're rejecting paying customers who did nothing wrong. A limit that's wrong in the strict direction is an outage you inflicted on yourself.
- **The synchronised-retry stampede.** This is the subtle one. If everyone you rejected obeys the same `Retry-After` of "2 seconds," then in two seconds they *all* come back at once — you've just rebuilt the spike you were trying to flatten. The fix is **jitter**: spread retries over a random interval around the target so they smear out instead of synchronising. Any retry policy without jitter is a thundering herd waiting to happen.
- **Global vs per-user is a real choice, not a default.** A single global limit is simple but lets one abuser starve everyone; per-user is fairer but can't, by itself, protect a fragile shared resource from the *sum* of many well-behaved users. Most real systems need both, and deciding which limit bites first is a design decision, not an afterthought.

Rate limiting is one of those tools that's trivial to bolt on and genuinely hard to get right. The algorithms in §3 are the easy part — they're a few lines each. The hard parts are choosing the identity in §2, paying the distributed tax in §5 honestly, and not turning your own limiter into the outage in §7.
