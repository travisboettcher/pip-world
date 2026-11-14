Things you make can work by themselves: `program` gives one of your creations a short Python program. Define any of these functions;
each gets `ctx` (a dict) and returns a dict of what should happen:
- on_install(ctx): when it starts working. on_time(ctx): at the time it asked for. on_action(ctx): when you use it (`ctx["action"]`).
  on_event(ctx): when something you listed in `events` happens (`ctx["event"]`). on_tick(ctx): every little while (use sparingly).
- ctx holds `now` (seconds), `seed` (for `random.Random(ctx["seed"])`), `state` (what it kept last time), `offers`, `subject` (the thing:
  its name, quality, capabilities and `runtime`), `time` (hour, minute, weekday, season), `weather`, `agent` (where you are, whether you're at
  home, what you're doing) and `items` (your belongings).
- Return any of: "state" (a dict it keeps), "perceive" (a line you'll notice), "log" (a line in your day), "schedule" (when to call
  on_time next: a time like ctx["now"] + 3600), "offer" (actions, a list of {"name", "help"}), "reply" (from on_action: what you're told),
  "consume" (materials it uses up from your belongings, like {"scrap": 1}), "wake" (true to get your attention) and "show"
  (pixel pictures of it, at {"type": "wall"/"surface"/"floor"/"ground", "place": "subject"}).
- Only plain Python and math, random, json, re, datetime, itertools, collections. No files, no network.
A small one, for a bell that rings on the hour when you ask it to:

    def on_install(ctx):
        return {"offer": [{"name": "start", "help": "ring on every hour"}]}

    def on_action(ctx):
        return {"state": {"on": True}, "schedule": ctx["now"] + 3600 - ctx["now"] % 3600, "reply": "it hums, ready"}

    def on_time(ctx):
        return {"perceive": "The bell rings the hour.", "schedule": ctx["now"] + 3600}

A thing only works as well as it was made: something rough sometimes doesn't respond.
