import asyncio
import hashlib
import json
import time

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from cache import TTLCache, prompt_key

app = FastAPI(title="Caching Demo — System Design Topic 02")

response_cache = TTLCache(ttl_seconds=30.0)

AGENTS = [
    {"id": 1, "name": "Researcher", "model": "claude-opus-4-7"},
    {"id": 2, "name": "Coder", "model": "claude-sonnet-4-6"},
]


def agents_etag() -> str:
    raw = json.dumps(AGENTS, sort_keys=True).encode()
    return '"' + hashlib.sha256(raw).hexdigest()[:16] + '"'


class Prompt(BaseModel):
    prompt: str


async def expensive_llm_call(prompt: str) -> str:
    await asyncio.sleep(1.0)
    return f"A thoughtful answer to: {prompt!r}"


@app.get("/agents")
def list_agents(request: Request):
    etag = agents_etag()
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "public, max-age=60"})
    return JSONResponse(
        AGENTS,
        headers={"ETag": etag, "Cache-Control": "public, max-age=60"},
    )


@app.post("/chat")
async def chat(body: Prompt):
    key = prompt_key(body.prompt)
    start = time.monotonic()

    cached = response_cache.get(key)
    if cached is not None:
        took_ms = int((time.monotonic() - start) * 1000)
        return {"cached": True, "took_ms": took_ms, "answer": cached}

    answer = await expensive_llm_call(body.prompt)
    response_cache.set(key, answer)
    took_ms = int((time.monotonic() - start) * 1000)
    return {"cached": False, "took_ms": took_ms, "answer": answer}


@app.post("/chat/invalidate")
def invalidate(body: Prompt):
    busted = response_cache.invalidate(prompt_key(body.prompt))
    return {"busted": busted}


@app.post("/chat/clear")
def clear():
    return {"cleared": response_cache.clear()}


@app.get("/health")
def health():
    return {"ok": True}


"""
## Explanation of the parts of the code

This file is one FastAPI process showing three different caches living at three different layers, because that is the thing the topic-01 README left dangling — it complained that GraphQL forfeits HTTP caching, and here is what HTTP caching actually buys you when you keep a plain REST GET.

`GET /agents` is the HTTP-caching layer, and it is the cheapest cache there is because the server barely participates. I compute an `ETag` — a short fingerprint of the response body — and send it alongside a `Cache-Control: max-age=60`. The browser, a CDN, or a reverse proxy can now hold that response for a minute without asking me anything. When the cache does re-check, it sends the fingerprint back in `If-None-Match`; if it still matches, I return a bare `304 Not Modified` with no body at all. That is the whole win: the client keeps using the copy it already has, and I send zero bytes of payload. A GraphQL endpoint cannot do this for free, because every query is a POST to one URL, and POSTs are not cacheable by the HTTP machinery — that is the exact trade topic 01 pointed at.

`POST /chat` is the application-cache layer, and it is cache-aside in the flesh. The `expensive_llm_call` sleeps a full second to stand in for a real model call that costs money and latency. Before paying that cost I normalise the prompt into a key and ask the cache. On a miss I do the slow work once, store it, and return `cached: false` with a `took_ms` up near a thousand. On the next identical prompt I get a hit and return in basically zero milliseconds with `cached: true`. The response carries those two fields specifically so you can *see* the cache working from `curl` instead of taking my word for it — the latency collapse is the entire point of the layer.

`POST /chat/invalidate` and `POST /chat/clear` are the unglamorous but essential other half. A cache that you can only write to is a cache that will eventually serve a stale lie, because the world behind the key changes. `invalidate` busts one prompt's cached answer — that is what you would call when the conversation context that produced the answer changed underneath you. `clear` is the demo's reset button. In a real system this is where most of the thinking goes: pick TTLs that match how fast the underlying data moves, bust explicitly on writes, or version your keys. The endpoints are tiny; the discipline they represent is not.

`GET /health` stays for the same reason it did in topic 01 — every server I ship has one, and orchestrators expect it.
"""
