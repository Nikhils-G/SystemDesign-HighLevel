from dataclasses import dataclass, field
from typing import List, Optional
import strawberry


@dataclass
class _Store:
    conversations: List[dict] = field(default_factory=lambda: [
        {"id": 1, "title": "First chat", "messages": []},
        {"id": 2, "title": "Debugging session", "messages": []},
    ])
    agents: List[dict] = field(default_factory=lambda: [
        {"id": 1, "name": "Researcher", "model": "claude-opus-4-7"},
        {"id": 2, "name": "Coder", "model": "claude-sonnet-4-6"},
    ])

    def append_message(self, conversation_id: int, role: str, text: str):
        for c in self.conversations:
            if c["id"] == conversation_id:
                c["messages"].append({"role": role, "text": text})
                return


store = _Store()


@strawberry.type
class Message:
    role: str
    text: str


@strawberry.type
class Conversation:
    id: int
    title: str

    @strawberry.field
    def messages(self) -> List[Message]:
        for c in store.conversations:
            if c["id"] == self.id:
                return [Message(**m) for m in c["messages"]]
        return []


@strawberry.type
class Agent:
    id: int
    name: str
    model: str


@strawberry.type
class Query:
    @strawberry.field
    def conversations(self) -> List[Conversation]:
        return [Conversation(id=c["id"], title=c["title"]) for c in store.conversations]

    @strawberry.field
    def conversation(self, id: int) -> Optional[Conversation]:
        for c in store.conversations:
            if c["id"] == id:
                return Conversation(id=c["id"], title=c["title"])
        return None

    @strawberry.field
    def agents(self) -> List[Agent]:
        return [Agent(**a) for a in store.agents]


@strawberry.type
class Mutation:
    @strawberry.mutation
    def add_message(self, conversation_id: int, text: str) -> Message:
        store.append_message(conversation_id, role="user", text=text)
        return Message(role="user", text=text)


schema = strawberry.Schema(query=Query, mutation=Mutation)


"""
## Explanation of the parts of the code

This file is the GraphQL layer for everything that *isn't* token streaming. The `_Store` dataclass at the top is deliberately a tiny Python object with two lists — one for conversations, one for agents. In a real app this would be a database; for a learning demo, an in-memory store keeps the focus on schema design instead of ORM noise. Both `app.py` and the GraphQL resolvers below import the same `store` instance, so a write from either side is immediately visible to the other. That shared-state trick is exactly what makes the hybrid feel seamless when you query GraphQL right after a chat stream finishes.

The Strawberry types map almost one-to-one to what a client would actually want to query. `Message` and `Agent` are flat — just primitive fields. `Conversation` is the interesting one because instead of a plain `messages` field, it has a `messages` *resolver*. That resolver is what makes nested queries work: when a client asks for `conversations { messages { text } }`, GraphQL calls our function for each conversation and we return the messages from the store. This is also the spot where, in a real app, the famous N+1 problem would show up — you would want a DataLoader to batch the per-conversation lookups into a single DB call. With one in-memory list it does not matter, but the *shape* is the same shape you would debug at scale, which is the lesson worth remembering.

The `Query` type is the read surface. Three resolvers: list all conversations, fetch one by id, list all agents. Each is a pure function that pokes at the store. The `Mutation` type is the write surface — `add_message` lets a client append a user message to a specific conversation. In a fuller app you would also have `createConversation`, `deleteMessage`, `updateAgent` and so on, but one mutation is enough to show the pattern.

At the bottom, `strawberry.Schema(query=Query, mutation=Mutation)` is what stitches everything together into a single schema object. That object is what `app.py` mounts at `/graphql`. The moment you hit that URL in a browser, Strawberry serves up GraphiQL — an interactive query explorer that reads the schema and shows you every type, every field, every argument, with autocomplete. That self-describing quality is another reason GraphQL is interesting for AI agents: an LLM can introspect the schema and figure out what is available without you ever writing tool documentation by hand.
"""
