# Concept 01 — Why I went hybrid (REST + GraphQL) for an AI chat backend

## The thing I was actually trying to figure out

I have a FastAPI app running AI chat agents. The chat itself works — a user sends a prompt, the model streams tokens back, the browser prints them as they arrive. The bigger picture started bugging me though: *do I just keep adding REST endpoints for everything else, or is GraphQL going to make my life better?*

So I sat down and built a tiny version of both, in one app, to see where each one earns its keep. This is what I learned, written down before I forget.

## The two pains REST gave me

Imagine the chat sidebar. To render it, the browser needs:

1. The user object (avatar, name)
2. The user's list of conversations
3. The last message of each conversation (for the preview line under each title)

In REST that's typically:

- `GET /me` → user
- `GET /me/conversations` → list of conversation IDs
- `GET /conversations/{id}/last-message` → run this N times, once per conversation

That's `1 + 1 + N` round trips. Three on a good day, fifteen on a bad one. And on top of that, `GET /me` returns 40 fields when I only needed two — `name` and `avatar`. The classic over-fetching plus under-fetching combo.

GraphQL flips it:

```graphql
query {
  me {
    name
    avatar
    conversations {
      id
      title
      lastMessage { text createdAt }
    }
  }
}
```

One round trip. Exactly the fields I asked for. That's the magic, and it's real.

## Where GraphQL stops being magic

I have to be honest about the tax:

- **Caching mostly evaporates.** REST gets free CDN and browser caching because each URL maps to a resource. GraphQL is a single POST to `/graphql` with a body — your CDN can't tell two different queries apart. You end up needing persisted queries or an Apollo-style client cache.
- **The N+1 trap.** A query like `posts { author { name } }` will, naively, hit the database once for posts and N more times to fetch each author. You need DataLoader-style batching. It's not optional in production, and it bites people who don't expect it.
- **Auth gets harder.** REST: protect endpoints. GraphQL: protect every field on every type, because the client can compose any path through the graph. You can't grep for `@require_auth` and call it a day.
- **Per-request parsing overhead.** Every query gets parsed, validated against the schema, then resolved. A simple REST `GET` is faster end-to-end for a single small read.

So GraphQL isn't free. It's a trade.

## The thing I almost got wrong: streaming

My first instinct was: GraphQL has *Subscriptions*, so I should stream LLM tokens through them. I went looking and… it's a mess. Subscriptions traditionally run over WebSockets via `graphql-ws`. There are also `@stream` and `@defer` directives, but tooling support is uneven across servers and clients, and there's no one obvious blessed pattern for streaming an LLM.

Then I noticed the elephant in the room: **OpenAI, Anthropic, and basically every LLM provider streams tokens over plain HTTP using Server-Sent Events**. Not WebSockets. Not GraphQL Subscriptions. Just `text/event-stream`.

Why? Because token streaming is *one-way* — server pushing to client, never the other direction. SSE is exactly that. It runs over normal HTTP, works through every CDN and reverse proxy, has built-in browser auto-reconnect via `EventSource`, and FastAPI supports it with literally one line (`StreamingResponse(generator, media_type="text/event-stream")`). It's boring and it just works. WebSockets and Subscriptions add bidirectional complexity I don't need for a one-way token firehose.

That settled it for me. **Streaming is REST + SSE. Period.**

## So what is GraphQL actually good for in my app?

The data plane *around* the chat:

- Conversation history
- Agent configurations (which model, which tools, which system prompt)
- User memory entries
- Tool definitions
- Settings, preferences, anything with relations

Especially because I might end up with multiple frontends — web, mobile, maybe a VS Code extension — each wanting differently shaped slices of the same data. That's exactly the case GraphQL was built for.

There's also a forward-looking angle that I think matters more every month: **the GraphQL schema can act as the agent's tool catalog**. Instead of giving the LLM 40 hand-crafted REST tool definitions, you expose the schema and let the agent compose precise queries against it. Apollo and others are pushing this hard. I'm not building that yet, but it's a reason to keep the GraphQL surface in the architecture from day one rather than bolting it on later.

## The hybrid in this folder, mapped to the code

`app.py` is the entrypoint. It does two things:

1. **Mounts GraphQL** at `/graphql` using `strawberry.fastapi.GraphQLRouter`. The schema lives in `schema.py`. This is the data plane — conversation history, agents, message queries.
2. **Exposes `POST /chat/stream`** — a normal REST endpoint that returns a `StreamingResponse` with `text/event-stream`. This is the hot path. The "LLM" here is faked with `asyncio.sleep` and a token list, but the *shape* of the code is identical to what you'd write against a real OpenAI or Anthropic streaming SDK.

`schema.py` is the GraphQL layer. I defined three types — `Conversation`, `Message`, `Agent` — a `Query` type for reads, and a `Mutation` type for writes. The store is an in-memory Python dataclass because persistence is a separate concern; I wanted the lesson to be about API shape, not about ORMs.

Both surfaces share the same `store` object. So when the SSE endpoint appends a message to conversation 1, a GraphQL query for that conversation immediately sees the new message. That's the *whole point* of the hybrid: same data, two access shapes, each playing to its strength. There's no syncing layer, no eventual-consistency dance — they're literally the same dict in memory.

## What I'd say to past-me

Don't migrate everything to GraphQL because it's the new shiny. Don't ignore it because REST is comfortable. Look at *where the pain actually is*. If your client is making three calls to render one screen, GraphQL probably earns its keep. If your hot path is server-pushed bytes, REST + SSE is the right tool and you should stop overthinking it.

Most production AI apps end up running pretty much the shape that's in this folder. That's not an accident — it's the shape that falls out when you let each tool do what it's good at.
