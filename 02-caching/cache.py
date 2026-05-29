import re
import time


def prompt_key(prompt: str) -> str:
    normalised = re.sub(r"\s+", " ", prompt.strip().lower())
    return normalised


class TTLCache:
    def __init__(self, ttl_seconds: float = 30.0):
        self.ttl = ttl_seconds
        self._data: dict[str, tuple[object, float]] = {}

    def get(self, key: str):
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() >= expires_at:
            del self._data[key]
            return None
        return value

    def set(self, key: str, value: object):
        self._data[key] = (value, time.monotonic() + self.ttl)

    def invalidate(self, key: str) -> bool:
        return self._data.pop(key, None) is not None

    def clear(self) -> int:
        count = len(self._data)
        self._data.clear()
        return count


"""
## Explanation of the parts of the code

This module is the whole caching primitive for the topic, and I kept it dependency-free on purpose. The temptation with a caching demo is to immediately reach for Redis, but then half the lesson becomes "how do I run Redis" instead of "what is a cache actually doing". A dict with timestamps captures the real behaviour, and the production version is the same shape — you just swap the dict for a network call.

`prompt_key` is the part people skip and then regret. Two users asking `"Hello"` and `"  hello "` are, for caching purposes, asking the same thing — but a naive cache keyed on the raw string sees two different keys and misses both times. So I normalise: strip the ends, lowercase, and collapse any run of whitespace down to a single space. That is the *exact-match* school of prompt caching. It is dumb in the good way — fast, predictable, no false hits. The smarter version is semantic caching, where you embed the prompt and match on cosine similarity so that "what's the capital of France" and "tell me France's capital" share an answer. That trades a little correctness risk (a false hit returns a wrong-but-plausible answer) for a much higher hit rate, and I left it out of the code on purpose so the concept doc can explain the trade instead of the code hiding it.

`TTLCache` is cache-aside in miniature. The store is `key -> (value, expires_at)`. The interesting decision is *lazy expiry*: I do not run a background sweeper deleting old keys. Instead `get` checks the clock on the way out, and if the entry is past its expiry it deletes it then and returns a miss. This is exactly how Redis behaves for most keys — it would be wasteful to actively scan millions of entries when you can just check staleness at read time, which is the only moment you actually care. I use `time.monotonic()` rather than wall-clock time because monotonic never jumps backwards when the system clock is adjusted; for measuring "has TTL elapsed" that is the correct clock.

`invalidate` and `clear` are the write-side of the contract. Caching is easy until something changes underneath you, and then invalidation is the entire game. `invalidate` busts one key — that is what you call when the thing behind that key changed. `clear` is the blunt instrument for the demo's reset endpoint. At scale this is where the real design work lives: TTLs that match how fast the underlying data moves, explicit busts on write, or versioned keys so a bumped version makes every old entry unreachable at once. The class is small, but the two methods at the bottom are the ones that decide whether your cache ever serves a stale lie.
"""
