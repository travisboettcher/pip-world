"""The dashboard's view of the whole world (docs/DESIGN-dashboard.md): everyone at a glance, what happens between the agents, and the
world's own doings. Only what anyone could see of an agent from outside: where they are, what they're doing, how they are, their tokens;
never anything of their mind."""
import json

from . import places, stakes
from .world_view import stat_list

AUTHORS = {"world": "by the world", "library": "shipped"}


def session(state) -> dict | None:
    """What the agent is busy with in real time (a walk, a module's session), for a page to show."""
    s = state.session()
    return {"kind": s["kind"], "about": s["about"], "label": s["expect"], "target": s["target"], "started_at": s["started_at"],
            "ends_at": s["ends_at"]} if s else None


def glance(world) -> list[dict]:
    """Each agent as anyone could see them, side by side."""
    out = []
    for a in world.agents:
        with a.acting():
            me = a.state.agent()
            out.append({"key": a.identity.key, "name": a.identity.name, "kind": a.identity.kind, "where": me["location"],
                        "place": places.label(me["location"]), "activity": me["activity"], "description": me["description"],
                        "mood": me["mood"], "asleep": me["activity"] == "sleeping", "stats": stat_list(a.state, a.s),
                        "condition": stakes.condition(a.state), "session": session(a.state), "usage": a.state.usage_today()})
    return out


def between(world, limit: int = 60) -> dict:
    """What happens between the agents, newest first: their meetings (once each), what one said to another, the letters they sent each
    other (and what was tucked in); and the post still on its way."""
    agents = list(world.agents)
    names = {a.identity.name: i for i, a in enumerate(agents)}
    out = []
    for i, a in enumerate(agents):
        for e in a.state.events_of(("met", "say", "letter_sent"), limit=limit * 4):    # most of an agent's says are to no one in particular
            d, who = e["data"], a.identity.name
            if e["kind"] == "met" and names[d["name"]] > i:                              # both remember it: once, from the first of the two
                out.append({"ts": e["ts"], "kind": "met", "who": who, "to": d["name"], "text": "", "place": d["place"]})
            elif e["kind"] == "say" and d["to_name"] in names:
                out.append({"ts": e["ts"], "kind": "said", "who": who, "to": d["to_name"], "text": d["text"]})
            elif e["kind"] == "letter_sent" and d["to"] in names:
                out.append({"ts": e["ts"], "kind": "letter", "who": who, "to": d["to"], "text": d["text"], "enclosed": d["enclosed"]})
    out.sort(key=lambda x: x["ts"], reverse=True)
    by_key = {a.identity.key: a.identity.name for a in agents}
    way = []
    for r in agents[0].state.db.execute("SELECT * FROM agent_post WHERE delivered_at IS NULL ORDER BY deliver_at").fetchall():
        way.append({"who": by_key.get(r["sender"], r["sender"]), "to": by_key.get(r["recipient"], r["recipient"]), "text": r["text"],
                    "enclosed": json.loads(r["enclosed"])["name"] if r["enclosed"] else "", "sent": r["sent_at"], "arrives": r["deliver_at"]})
    return {"happened": out[:limit], "on_the_way": way}


def _doing(e, who: str) -> str:
    d = e["data"]
    if e["kind"] == "builder":
        if d["outcome"] == "proposed":
            return f"The builder proposed {d['name']}" + (" (a new version)" if d.get("revised") else "")
        if d["outcome"] == "dropped":
            return f"The builder dropped an idea ({d['name']}): {d['why']}"
        return f"The builder {'added nothing' if d['outcome'] == 'nothing' else 'could not propose anything'}: {d['why']}"
    if e["kind"] == "module_live":
        return f"{d['name']} v{d['version']} ({AUTHORS.get(d['author'], f'by {who}')}) is live"
    if e["kind"] == "module_disabled":
        return f"{d['name']} was switched off" + (f": {d['why']}" if d["why"] else "")
    if e["kind"] == "module_rejected":
        return f"{d['name']} v{d['version']} was turned down" + (f": {d['note']}" if d["note"] else "")
    return f"{d['name']} ({d['role']}) came into the world: {d['about']}"


def doings(world, limit: int = 40) -> dict:
    """The world's own doings, newest first: the builder's nights, modules going live, off or turned down, and the people the world
    brought (once each, whoever saw them come); and the modules whose recent calls fail."""
    seen, out = set(), []
    for a in world.agents:
        for e in a.state.events_of(("builder", "module_live", "module_disabled", "module_rejected", "character"), limit=limit):
            text = _doing(e, a.identity.name)
            key = (e["kind"], text) if e["kind"] == "character" else (e["kind"], text, e["ts"])
            if key not in seen:
                seen.add(key)
                out.append({"ts": e["ts"], "kind": e["kind"], "text": text, "who": a.identity.name})
    out.sort(key=lambda x: x["ts"], reverse=True)
    failing, db = [], world.agents[0].state.db
    for r in db.execute("SELECT m.id, m.name, m.version, COUNT(*) AS calls, SUM(1 - c.ok) AS failed FROM module_calls c "
                        "JOIN modules m ON m.id = c.module_id GROUP BY m.id HAVING failed > 0").fetchall():
        last = db.execute("SELECT summary, ts FROM module_calls WHERE module_id = ? AND ok = 0 ORDER BY id DESC LIMIT 1", (r["id"],)).fetchone()
        failing.append({"name": r["name"], "version": r["version"], "calls": r["calls"], "fails": r["failed"], "last": last["summary"],
                        "last_ts": last["ts"]})
    failing.sort(key=lambda m: m["last_ts"], reverse=True)
    return {"happened": out[:limit], "failing": failing}
