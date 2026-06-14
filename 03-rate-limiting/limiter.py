import time
from collections import deque
from dataclasses import dataclass


@dataclass
class Decision:
    allowed: bool
    remaining: int
    retry_after: float
    limit: int


class TokenBucket:
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)
        self.updated = time.monotonic()

    def allow(self) -> Decision:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.refill_rate)
        self.updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return Decision(True, int(self.tokens), 0.0, self.capacity)
        retry_after = (1 - self.tokens) / self.refill_rate
        return Decision(False, 0, retry_after, self.capacity)


class SlidingWindow:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self.hits: deque[float] = deque()

    def allow(self) -> Decision:
        now = time.monotonic()
        while self.hits and now - self.hits[0] >= self.window:
            self.hits.popleft()
        if len(self.hits) < self.limit:
            self.hits.append(now)
            return Decision(True, self.limit - len(self.hits), 0.0, self.limit)
        retry_after = self.window - (now - self.hits[0])
        return Decision(False, 0, retry_after, self.limit)


class Limiter:
    def __init__(self, factory):
        self.factory = factory
        self._buckets: dict[str, object] = {}

    def check(self, client_id: str) -> Decision:
        bucket = self._buckets.get(client_id)
        if bucket is None:
            bucket = self.factory()
            self._buckets[client_id] = bucket
        return bucket.allow()


"""
## Explanation of the parts of the code

This module is the rate-limiting engine, and like the cache in topic 02 I kept it dependency-free so the lesson is the algorithm, not the plumbing. Both limiters return the same little `Decision` so `app.py` never has to care which algorithm is behind a route — it just reads `allowed`, `remaining`, and `retry_after` and turns them into a response.

`TokenBucket` is the one I reach for by default, and it is worth understanding *why* it feels right for an API. The mental picture: a bucket holds up to `capacity` tokens and refills at `refill_rate` tokens per second. Every request spends one token; if the bucket is empty the request is denied. The clever part is that I do not run a background timer dripping tokens in — that would be a thread doing nothing useful most of the time. Instead, on each call I look at how long it has been since the last call and add exactly that many seconds' worth of tokens, capped at the brim. That lazy refill is mathematically identical to a constant drip but costs nothing between requests. The behaviour you get is the behaviour you actually want from an API: a client can *burst* — fire five requests back to back if the bucket was full — but cannot sustain more than `refill_rate` over time. Bursts are fine; a firehose is not. When it does deny, I compute exactly how long until one whole token will have refilled and hand that back as `retry_after`, so the client knows precisely when to come back.

`SlidingWindow` is the stricter sibling, and it exists here to contrast with the bucket. It keeps a timestamp for every recent hit in a `deque`, throws away anything older than the window on each call, and allows the request only if fewer than `limit` hits remain inside the window. There is no burst allowance beyond the raw count — three per ten seconds means three per ten seconds, measured continuously. This is the fix for the classic fixed-window bug, where a client sneaks the full quota into the last instant of one window and the full quota into the first instant of the next, doubling the intended rate at the seam. By measuring against a window that slides with *now* instead of snapping to clock boundaries, that loophole closes. The cost is memory: I store one timestamp per request in the window, where the token bucket stores two floats no matter how much traffic flows. That memory-vs-smoothness trade is the whole reason both algorithms exist.

`Limiter` is the small piece that makes either algorithm multi-tenant. A single bucket would rate-limit the entire world as one client, which is never what you want — one noisy user would lock out everyone. So `Limiter` holds a dict of `client_id -> bucket` and lazily mints a fresh bucket the first time it sees a new client, using whatever factory it was handed. That is what gives every API key its own independent budget. The thing this design quietly assumes is a *single process*: the dict lives in one server's memory, so the moment you run two instances behind a load balancer each keeps its own half-blind count and a client effectively gets double the limit. Fixing that means moving the counter into shared state like Redis, which is exactly the distributed-limiting discussion in `concept3.md`.
"""
