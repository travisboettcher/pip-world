"""Server-Sent Events: push new events to the browser as they are logged."""
import asyncio
import json
from typing import Awaitable, Callable

from .state import State

KEEPALIVE_EVERY = 15  # idle polls between ": keepalive" comments


async def event_stream(state: State, cur: int, disconnected: Callable[[], Awaitable[bool]],
                       interval: float = 1.0, max_polls: int | None = None,
                       transform: Callable[[dict], dict | None] | None = None):
    """Yield SSE frames for events with id > cur. `id:` lets the browser resume after a reconnect. `transform` may trim an event or
    return None to skip it (the public view); the cursor still moves past skipped events."""
    yield "retry: 3000\n\n"
    idle = polls = 0
    while not await disconnected():
        events = state.events(limit=200, after_id=cur)
        for e in events:
            cur = e["id"]
            shown = transform(e) if transform else e
            if shown:
                yield f"id: {cur}\ndata: {json.dumps(shown)}\n\n"
        idle = 0 if events else idle + 1
        if idle and idle % KEEPALIVE_EVERY == 0:
            yield ": keepalive\n\n"
        polls += 1
        if max_polls is not None and polls >= max_polls:
            return
        await asyncio.sleep(interval)
