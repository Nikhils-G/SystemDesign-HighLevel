import asyncio

from fastapi import Depends, FastAPI, HTTPException, Request, Response

from limiter import Limiter, SlidingWindow, TokenBucket

app = FastAPI(title="Rate Limiting Demo — System Design Topic 03")

chat_limiter = Limiter(lambda: TokenBucket(capacity=5, refill_rate=1.0))
search_limiter = Limiter(lambda: SlidingWindow(limit=3, window_seconds=10.0))


def client_id(request: Request) -> str:
    key = request.headers.get("x-api-key")
    if key:
        return f"key:{key}"
    return f"ip:{request.client.host}"


def rate_limit(limiter: Limiter):
    def dependency(request: Request, response: Response):
        decision = limiter.check(client_id(request))
        response.headers["X-RateLimit-Limit"] = str(decision.limit)
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Slow down.",
                headers={
                    "Retry-After": str(round(decision.retry_after, 2)),
                    "X-RateLimit-Limit": str(decision.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )
        return decision

    return dependency


@app.post("/chat")
async def chat(_: object = Depends(rate_limit(chat_limiter))):
    await asyncio.sleep(0.2)
    return {"answer": "a thoughtful, expensive answer"}


@app.get("/search")
def search(_: object = Depends(rate_limit(search_limiter))):
    return {"results": ["alpha", "beta", "gamma"]}


@app.get("/health")
def health():
    return {"ok": True}


"""
## Explanation of the parts of the code

This file is one FastAPI process showing rate limiting as it actually ships: not one global cap, but per-client budgets enforced per route, with the polite HTTP contract that lets well-behaved clients back off on their own. It leans entirely on the two algorithms from `limiter.py` and spends its own code on the parts that are FastAPI's job — identifying the caller and shaping the response.

`client_id` is the unglamorous function that everything else depends on, and it is the part people underthink. A rate limiter is only as good as its notion of *who*. I prefer the `X-API-Key` header when it is present because a key identifies an account no matter where it connects from, and I fall back to the client IP when there is no key. The IP fallback is deliberately a weak last resort: a whole office or a mobile carrier can sit behind one address, so IP-keying punishes innocents who share it, and a determined abuser can rotate addresses anyway. Naming this trade in code is the point — in a real system the key is the thing you trust and the IP is the thing you tolerate.

`rate_limit` is a dependency *factory*, which is the small trick that lets two routes share one enforcement path while keeping separate budgets. Calling `rate_limit(chat_limiter)` builds a dependency bound to the chat bucket; `rate_limit(search_limiter)` builds one bound to the search window. FastAPI runs whichever the route declared before the handler body, so the limit check happens up front and the expensive work below never runs for a request that is going to be rejected. On every outcome I stamp `X-RateLimit-Limit` and `X-RateLimit-Remaining` onto the response so a client can watch its own budget drain in real time. On a denial I raise a `429 Too Many Requests` carrying a `Retry-After` — the exact number of seconds until the limiter will say yes again. That header is the difference between a client that waits the right amount and one that hammers you in a tight retry loop making everything worse.

The two protected routes are chosen to contrast the algorithms. `POST /chat` sits behind a token bucket of capacity five refilling one per second, which models an expensive LLM call you are happy to let a user burst — fire a few in a row — but not stream forever. `GET /search` sits behind a sliding window of three per ten seconds, a strict steady drip with no burst slack, so you can fire both endpoints side by side and feel the personalities differ. `GET /health` stays unprotected, because a health check that can be rate-limited is a health check that lies to your load balancer exactly when traffic is highest.
"""
