"""What makes talk read like talk, shared by every kind of conversation in the world: a check for saying the same thing twice, and the
transcripts Pip is shown of a visit and of a chat with a visitor (see docs/DESIGN-conversation.md)."""
import difflib
import re

SHINGLE = 6           # a run of this many words said before is a repeat
SIMILAR = 0.8         # or a line this alike as a whole
THREAD_LINES = 10     # lines of a chat with a visitor Pip is shown
THREAD_DAYS = 3
VISIT_LINES = 8


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", re.sub(r"\*[^*]*\*", " ", str(text or "").lower()))


def repeats(text: str, earlier) -> bool:
    """Does `text` say again what one of the `earlier` lines said: a run of SHINGLE words in common, or nearly the same line? Stage directions in *asterisks* are left out."""
    words = _words(text)
    runs = {tuple(words[i:i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)}
    plain = " ".join(words)
    for other in earlier:
        theirs = _words(other)
        if runs & {tuple(theirs[i:i + SHINGLE]) for i in range(len(theirs) - SHINGLE + 1)}:
            return True
        if len(words) >= 5 and difflib.SequenceMatcher(None, plain, " ".join(theirs)).ratio() >= SIMILAR:     # a short "thank you" may come twice
            return True
    return False


def visit_lines(state, name: str, since: float) -> list[str]:
    """This visit, in full: what `name` and Pip have said to each other since Pip arrived (oldest first)."""
    out = []
    for e in reversed(state.events(200)):
        if e["ts"] < since:
            continue
        d = e["data"]
        if e["kind"] == "companion" and d.get("name") == name:
            out.append(f"{name}: {d['text']}")
        elif e["kind"] == "say" and d.get("to_name") == name:
            out.append(f"You: {d['text']}")
    return out[-VISIT_LINES:]


def thread_lines(state, sender: str, now: float, skip_ids=()) -> list[str]:
    """A chat with a visitor so far (oldest first): what they wrote, what Pip answered, and the postcards Pip sent on the channel they write on.
    Messages in `skip_ids` (shown as the inbox) are left out."""
    events = [e for e in reversed(state.events(400)) if now - e["ts"] <= THREAD_DAYS * 86400]
    theirs = [e["data"] for e in events if e["kind"] == "inbox" and e["data"].get("sender") == sender
              and not e["data"].get("gift") and not e["data"].get("letter")]
    ids = {d.get("id") for d in theirs}
    channels = {d.get("source") or "web" for d in theirs}
    out = []
    for e in events:
        d = e["data"]
        if e["kind"] == "inbox" and d.get("sender") == sender and not d.get("gift") and not d.get("letter"):
            if d.get("id") not in skip_ids:
                out.append(f"{sender}: {d['text']}")
        elif e["kind"] == "say" and not d.get("to_name") and set(d.get("to") or []) & ids:
            out.append(f"You: {d['text']}")
        elif e["kind"] == "outreach" and d.get("what") == "postcard" and d.get("delivered") and d.get("channel") in channels:
            out.append(f"You (a postcard you sent): {d['text']}")
    return out[-THREAD_LINES:]
