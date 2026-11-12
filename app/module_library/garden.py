# The garden (docs/DESIGN-world-packs.md, phase 4b): plots in this module's store, the `plant` and `harvest` tools, the weather's effect on
# growing, a status section the agent sees every time, and what other modules may ask of it: `hurry` (a creation that helps it along),
# `crop` (a happening's turn for one crop, sized by its severity) and `add_plot` (a lasting change the agent made). The engine knows none
# of this: it only checks what this module proposes.
WEATHER = {"sunny": 0.95, "cloudy": 1.03, "rainy": 0.85, "pouring": 0.85, "lightning-rainy": 0.85, "snowy": 1.15, "snowy-rainy": 1.1,
           "fog": 1.05, "hail": 1.1}                            # growing-time multipliers: rain helps, cold and snow hinder (+-15%)
SHIFT = {"minor": 0.05, "medium": 0.15, "major": 0.30}          # a happening's share of a crop's time left
YIELD = {"minor": 1, "medium": 2, "major": 3}                   # a happening's change to what a crop gives
HURRY = (0.01, 0.2)                                             # the share of growing time a helper may take off


def _singular(word):
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("oes") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def _key(name):
    return " ".join(_singular(w) for w in str(name).lower().split())


def _span(minutes):
    minutes = int(minutes)
    return str(minutes) + " min" if minutes < 120 else str(round(minutes / 60)) + " hours"


def _count(ctx):
    p = ctx["params"]
    return min(p["plots_max"], p["plots"] + ctx["store"].get("meta", {}).get("extra_plots", 0))


def _plots(ctx):
    """Every plot in order: {plot, state ("empty", "growing", "ready"), and for a planted one its crop, seed, times, yield, food_value}."""
    stored, now, out = ctx["store"].get("plots", {}), ctx["now"], []
    for n in range(1, _count(ctx) + 1):
        p = stored.get(str(n))
        if not p:
            out.append({"plot": n, "state": "empty"})
            continue
        left = p["ready_at"] - now
        out.append(dict(p, plot=n, state="ready" if left <= 0 else "growing", ready_in_min=max(0, int(left // 60) + (1 if left % 60 else 0))))
    return out


def _view(ctx, plots, store=None):
    """What every call leaves behind: the status the agent sees, the facts others read, and when to look again."""
    now = ctx["now"]
    lines = []
    for p in plots:
        if p["state"] == "empty":
            lines.append("plot " + str(p["plot"]) + ": empty")
        elif p["state"] == "ready":
            lines.append("plot " + str(p["plot"]) + ": " + p["crop"] + " are RIPE - harvest them")
        else:
            lines.append("plot " + str(p["plot"]) + ": " + p["crop"] + " growing, ready in about {in:" + str(p["ready_at"]) + "}")   # the engine says how long
    growing = [p["ready_at"] for p in plots if p["state"] == "growing"]
    out = {"status": {"title": "Your garden", "lines": lines, "ready": any(p["state"] == "ready" for p in plots)},
           "publish": {"plots": [{k: p[k] for k in ("plot", "crop", "planted_at", "ready_at") if k in p} for p in plots],
                       "names": sorted({p["crop"] for p in plots if p["state"] != "empty"})},
           "schedule": min(growing) if growing else None}
    if growing:
        out["status"]["next_at"] = min(growing)
    if store:
        out["store"] = store
    return out


def _after(ctx, changes):
    """The plots as they will be once `changes` (to the plots collection) are made."""
    plots = dict(ctx["store"].get("plots", {}))
    for k, v in changes.items():
        if v is None:
            plots.pop(k, None)
        else:
            plots[k] = v
    return _plots(dict(ctx, store=dict(ctx["store"], plots=plots)))


def on_install(ctx):
    return _view(ctx, _plots(ctx))


def on_time(ctx):
    """A crop ripened: say so once (the agent is woken, and it's remembered), and look again at the next one."""
    plots, changes, out = _plots(ctx), {}, {}
    for p in plots:
        if p["state"] == "ready" and not p.get("notified"):
            changes[str(p["plot"])] = {k: p[k] for k in ("seed", "crop", "planted_at", "ready_at", "yield", "food_value")} | {"notified": True}
            out = {"log": {"text": "Your " + p["crop"] + " in plot " + str(p["plot"]) + " ripened", "kind": "ripe", "feel": {"joy": 3}},
                   "wake": True}
    view = _view(ctx, plots, {"plots": changes} if changes else None)
    view.update(out)
    return view


def _seed(ctx, query):
    seeds = [i for i in ctx["items"] if i["kind"] == "seed"]
    q = str(query).strip().lower()
    exact = [i for i in seeds if _key(i["name"]) == _key(q)]
    part = exact or [i for i in seeds if q and (q in i["name"].lower() or i["name"].lower() in q)]
    if len(part) == 1 or exact:
        return part[0], ""
    if not part:
        crop = q.removesuffix(" seeds").removesuffix(" seed")
        food = next((i for i in ctx["items"] if i["kind"] == "food" and _key(i["name"]) == _key(crop)), None)
        hint = "; you could scoop seeds out of your " + food["name"] + " with use_item (say what for)" if food else ""
        return None, "you don't have " + repr(str(query)) + " (kind: seed)" + hint
    return None, "which one? " + ", ".join(i["name"] for i in part)


def _plot_arg(ctx, plots):
    n = ctx["args"].get("plot")
    if n is None:
        return None, ""
    if not 1 <= n <= len(plots):
        return None, "plots are numbered 1-" + str(len(plots))
    return n, ""


def _plant(ctx):
    plots = _plots(ctx)
    item, err = _seed(ctx, ctx["args"]["seed"])
    if not item:
        return {"reply": "error: " + err}
    n, err = _plot_arg(ctx, plots)
    if err:
        return {"reply": "error: " + err}
    if n is None:
        free = [p["plot"] for p in plots if p["state"] == "empty"]
        if not free:
            return {"reply": "error: every plot is in use; harvest one first"}
        n = free[0]
    elif plots[n - 1]["state"] != "empty":
        return {"reply": "error: plot " + str(n) + " is already growing " + plots[n - 1]["crop"]}
    at, now = item["attrs"], ctx["now"]
    weather = (ctx.get("weather") or {}).get("condition")
    grow = float(at["grow_minutes"]) * WEATHER.get(weather, 1.0)
    planted = {"seed": item["name"], "crop": at["crop"], "planted_at": now, "ready_at": now + grow * 60 / ctx["params"]["speed"],
               "yield": int(at["yield"]), "food_value": float(at["food_value"]), "notified": False}
    out = _view(ctx, _after(ctx, {str(n): planted}), {"plots": {str(n): planted}})
    out["take"] = [{"item": item["name"], "qty": 1}]
    out["reply"] = ("planted " + item["name"] + " in plot " + str(n) + "; " + at["crop"] + " will be ready in about "
                    + _span(max(1, round(grow / ctx["params"]["speed"]))))
    return out


def _harvest(ctx):
    plots = _plots(ctx)
    n, err = _plot_arg(ctx, plots)
    if err:
        return {"reply": "error: " + err}
    ripe = [p for p in plots if p["state"] == "ready" and n in (None, p["plot"])]
    if not ripe:
        growing = [p for p in plots if p["state"] == "growing"]
        hint = "; next ready in about " + _span(min(p["ready_in_min"] for p in growing)) if growing else "; nothing is planted"
        return {"reply": "nothing ripe to harvest" + hint}
    p = ripe[0]
    out = _view(ctx, _after(ctx, {str(p["plot"]): None}), {"plots": {str(p["plot"]): None}})
    out["give"] = [{"item": p["crop"], "qty": p["yield"], "kind": "food", "description": "fresh " + p["crop"] + " from your garden",
                    "attrs": {"food_value": p["food_value"]}}]
    out["reply"] = "harvested " + str(p["yield"]) + " " + p["crop"] + " from plot " + str(p["plot"])
    return out


def on_action(ctx):
    return _plant(ctx) if ctx.get("tool") == "plant" else _harvest(ctx)


def _changed(p, **new):
    return {k: p[k] for k in ("seed", "crop", "planted_at", "ready_at", "yield", "food_value", "notified")} | new


def _hurry(ctx, share):
    now, changes = ctx["now"], {}
    for p in _plots(ctx):
        if p["state"] == "growing":
            changes[str(p["plot"])] = _changed(p, ready_at=p["ready_at"] - (p["ready_at"] - now) * share)
    if not changes:
        return {"refuse": "nothing is growing"}
    out = _view(ctx, _after(ctx, changes), {"plots": changes})
    out["reply"] = "helped " + str(len(changes)) + " growing crop" + ("" if len(changes) == 1 else "s") + " along"
    return out


def _crop(ctx, r):
    """A happening's turn for one crop: its time (sooner or later), what it gives (more or less), or (major, bad) the crop lost."""
    sign = 1 if r.get("tone") == "good" else -1
    severity, how = r.get("severity", "minor"), r["args"].get("how", "time")
    p = next((p for p in _plots(ctx) if p["plot"] == r["args"].get("plot") and p["state"] == "growing"), None)
    if not p:
        return {"refuse": "`plot` is the number of a plot with something growing"}
    name = "Plot " + str(p["plot"]) + "'s " + p["crop"]
    if how == "ruin":
        if sign > 0 or severity != "major":
            return {"refuse": "only a major bad turn ruins a crop"}
        change, line = None, name + " is lost."
    elif how == "time":
        shift = round(max(0.0, p["ready_at"] - ctx["now"]) / 60 * SHIFT[severity])
        if shift < 1:
            return {"refuse": "that crop is as good as ripe"}
        change = _changed(p, ready_at=ctx["now"] + (p["ready_at"] - ctx["now"]) * (1 - sign * SHIFT[severity]))
        line = name + " will be ready about " + _span(shift) + " " + ("sooner" if sign > 0 else "later") + "."
    elif how == "yield":
        delta = YIELD[severity] if sign > 0 else min(YIELD[severity], p["yield"] - 1)
        if delta < 1:
            return {"refuse": "that crop can't give any less"}
        change = _changed(p, **{"yield": p["yield"] + sign * delta})
        line = name + " will give " + str(delta) + " " + ("more" if sign > 0 else "less") + "."
    else:
        return {"refuse": "`how` is time, yield or ruin"}
    if not r["apply"]:
        return {"reply": line}
    out = _view(ctx, _after(ctx, {str(p["plot"]): change}), {"plots": {str(p["plot"]): change}})
    out["reply"] = line
    return out


def on_request(ctx):
    r = ctx["request"]
    if r["what"] == "hurry":
        share = r["args"].get("share", 0.1)
        if not isinstance(share, (int, float)) or not HURRY[0] <= share <= HURRY[1]:
            return {"refuse": "`share` is " + str(HURRY[0]) + " to " + str(HURRY[1])}
        return _hurry(ctx, share)
    if r["what"] == "crop":
        return _crop(ctx, r)
    if _count(ctx) >= ctx["params"]["plots_max"]:                  # add_plot
        return {"refuse": "the garden is as big as it can be"}
    grown = dict(ctx, store=dict(ctx["store"], meta={"extra_plots": ctx["store"].get("meta", {}).get("extra_plots", 0) + 1}))
    out = _view(grown, _plots(grown), {"meta": grown["store"]["meta"]})
    n = str(_count(grown))
    out["reply"] = "Your garden now has " + n + " plots: a new bed is ready for planting (plot " + n + ")."
    return out
