import asyncio
import json
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from strawberry.fastapi import GraphQLRouter

from schema import schema, store

app = FastAPI(title="Hybrid AI Agent API")
app.include_router(GraphQLRouter(schema), prefix="/graphql")


class Prompt(BaseModel):
    prompt: str
    conversation_id: int = 1


async def token_stream(prompt: str, conversation_id: int):
    reply = ["Hi", " there!", " You", " said:", f" '{prompt}'.", " Streaming", " back", " token", " by", " token.", " Done."]
    full = ""
    for tok in reply:
        full += tok
        yield f"data: {json.dumps({'token': tok})}\n\n"
        await asyncio.sleep(0.15)
    store.append_message(conversation_id, role="assistant", text=full)
    yield f"data: {json.dumps({'done': True})}\n\n"


@app.post("/chat/stream")
async def chat_stream(body: Prompt):
    store.append_message(body.conversation_id, role="user", text=body.prompt)
    return StreamingResponse(
        token_stream(body.prompt, body.conversation_id),
        media_type="text/event-stream",
    )


@app.get("/health")
def health():
    return {"ok": True}


"""
## Explanation of the parts of the code

The whole point of this file is to be a single FastAPI process that serves *two* very different kinds of API at once. Right at the top we wire in Strawberry's `GraphQLRouter` under `/graphql` — that's our entire GraphQL surface, and it pulls the schema in from `schema.py`. Mounting it on the same app is the whole hybrid trick: one process, one port, two API shapes living next to each other without stepping on each other's toes.

Below that lives the chat-streaming endpoint. The `Prompt` model is just there so FastAPI gives us automatic JSON validation — `prompt` is required, `conversation_id` defaults to 1 because in a real app you'd take it from auth, but for the demo we hardcode the default. The `token_stream` async generator is the heart of the streaming behaviour: it yields chunks one at a time, sleeps a beat between them so you can actually see the streaming happen in your terminal or browser, and assembles the full reply as it goes. Each `yield` produces a properly-formatted SSE frame — the `data:` prefix and the double newline matter; without them, browsers and `curl` won't recognise it as an event stream and will buffer everything until the connection closes.

When the stream finishes, we drop the assembled assistant reply into the same in-memory store that GraphQL reads from. That is the cute part of the hybrid: by the time the SSE stream ends, a GraphQL query for the same conversation will already see the new message. No syncing layer, no eventual-consistency dance — they are literally the same Python dict in memory.

The `StreamingResponse` wrapper is what makes FastAPI cooperate with the generator instead of buffering everything and sending it as one blob. The `media_type="text/event-stream"` tells the client (and any proxy in the way) to flush as it goes. That is the whole magic of SSE in FastAPI — there is no extra library, just an async generator and the right content type.

The `/health` endpoint is a throwaway. Every server I have ever shipped has had one, and load balancers and orchestrators expect it to exist, so it goes in from day one.
"""
