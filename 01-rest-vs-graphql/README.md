# REST vs GraphQL — System Design Topic 01

The first stop on the system-design journey. One question:
**should an AI-chat backend on FastAPI use REST, GraphQL, or both?**
Spoiler — both. This folder shows why and how, with a tiny working hybrid.

---

## 1. REST vs GraphQL — at a glance

| Dimension          | REST                                  | GraphQL                                  |
|--------------------|---------------------------------------|------------------------------------------|
| Endpoints          | many (`/users`, `/posts/1/comments`)  | one (`/graphql`)                         |
| Response shape     | server decides                         | client asks for the exact fields         |
| Schema             | optional (OpenAPI / Swagger)           | mandatory, strongly typed                |
| Caching            | free via HTTP / CDN                    | hard — needs persisted queries / Apollo  |
| Versioning         | `/v1`, `/v2`                           | deprecate fields in-place                |
| Best for           | streams, simple CRUD, public APIs      | varied client shapes, deep nested data   |

**Short rule of thumb:**
- **REST + SSE** → token streaming, anything server-pushed.
- **GraphQL** → varied data needs across many clients, deep relations, AI-agent tool catalogs.

---

## 2. What's in this folder

```
01-rest-vs-graphql/
├── README.md       this file — the 2-minute overview
├── concept1.md     the deep "why" — read after this
├── app.py          FastAPI app: REST + SSE + GraphQL mounted on one process
└── schema.py       Strawberry GraphQL schema (Conversation, Message, Agent)
```

**The hybrid in one sentence:** `POST /chat/stream` streams LLM tokens over SSE (REST's job), and `/graphql` handles conversation history, agents, and message queries (GraphQL's job). Same process. Same in-memory store. Two API shapes.

---

## 3. Concepts we touch

- REST endpoints in FastAPI (`@app.post`, Pydantic body models)
- Server-Sent Events (`text/event-stream`, `StreamingResponse`)
- GraphQL types, queries, mutations, resolvers
- Mounting GraphQL inside a FastAPI app via `strawberry.fastapi.GraphQLRouter`
- A single in-memory store shared by both surfaces
- Why streaming is REST's job, not GraphQL Subscriptions'

---

## 4. How to run

```bash
pip install fastapi uvicorn "strawberry-graphql[fastapi]"
uvicorn app:app --reload
```

Then poke at it:

- **GraphiQL UI** → http://localhost:8000/graphql
  ```graphql
  {
    conversations { id title messages { role text } }
    agents { name model }
  }
  ```
- **SSE stream test** (terminal):
  ```bash
  curl -N -X POST http://localhost:8000/chat/stream \
    -H "Content-Type: application/json" \
    -d '{"prompt":"hello","conversation_id":1}'
  ```
  You'll see `data: {...}` chunks arriving one at a time, then `data: {"done": true}`.

After the stream, run the GraphQL query again — the new messages will show up. That's the hybrid in action.

→ Open `concept1.md` for the full reasoning.

---

## 5. Sources I learned from

- [Strawberry GraphQL — FastAPI integration](https://strawberry.rocks/docs/integrations/fastapi) — how to mount GraphQL inside a FastAPI app
- [Strawberry API reference](https://strawberry.rocks/api-reference/) — `@strawberry.type`, `@strawberry.field`, `Schema`, etc.
- [FastAPI — GraphQL](https://fastapi.tiangolo.com/how-to/graphql/) — official note that Strawberry is the recommended pick
- [FastAPI — Server-Sent Events](https://fastapi.tiangolo.com/tutorial/server-sent-events/) — `StreamingResponse` + `text/event-stream`
- [GraphQL vs REST — AWS](https://aws.amazon.com/compare/the-difference-between-graphql-and-rest/) — clean side-by-side comparison
- [GraphQL.org — Subscriptions](https://graphql.org/learn/subscriptions/) — when subscriptions actually fit (and when they don't)
- [Apollo — Chatbots with GraphQL federation](https://www.apollographql.com/guides/chatbots) — the schema-as-tool-catalog idea for AI agents
- [AppSync + Bedrock streaming for conversational AI — AWS](https://aws.amazon.com/blogs/machine-learning/improve-conversational-ai-response-times-for-enterprise-applications-with-the-amazon-bedrock-streaming-api-and-aws-appsync/) — alternative architecture using subscriptions
- [GraphQL doesn't solve under/overfetching — HackerNoon](https://hackernoon.com/graphql-doesnt-solve-under-and-overfetching) — the honest counterpoint
