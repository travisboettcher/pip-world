"""Pip's pictures and writing (see DESIGN-art.md).

Pip draws by writing SVG itself. It is untrusted text that ends up in a browser and in a chat room, so it is never stored
or served as written: it is parsed with a strict whitelist (shapes, paths, text, gradients; no scripts, images, links,
styles, filters or references to anything outside the picture), size-limited, and re-serialised on a fixed canvas.
Anything that could do more than paint is rejected with a plain reason so Pip can fix it and try again.
"""
import re
import xml.etree.ElementTree as ET

from .channels import Image  # noqa: F401  (re-exported for callers building attachments)
from .text import clip

CANVAS = (400, 300)
MAX_BYTES = 24_000
MAX_ELEMENTS = 400
MAX_DEPTH = 12
MAX_ATTR = 4_000
MAX_WRITING = 2_000
SVG_NS = "http://www.w3.org/2000/svg"

ELEMENTS = {"svg", "g", "defs", "rect", "circle", "ellipse", "line", "polyline", "polygon", "path", "text", "tspan",
            "linearGradient", "radialGradient", "stop", "title", "desc"}
ATTRIBUTES = {
    "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "width", "height", "points", "d", "transform", "fill",
    "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-dasharray", "stroke-dashoffset", "stroke-miterlimit",
    "opacity", "fill-opacity", "stroke-opacity", "fill-rule", "font-size", "font-family", "font-weight", "font-style",
    "text-anchor", "dominant-baseline", "letter-spacing", "id", "offset", "stop-color", "stop-opacity", "gradientUnits",
    "gradientTransform", "fx", "fy", "spreadMethod", "dx", "dy", "viewBox", "preserveAspectRatio", "shape-rendering",
}
FORBIDDEN_ELEMENTS = {"script", "style", "image", "use", "foreignObject", "a", "iframe", "animate", "animateTransform", "set",
                      "filter", "feImage", "mask", "pattern", "symbol", "switch", "link", "audio", "video"}
DANGEROUS = re.compile(r"(javascript:|data:|https?:|//|@import|expression\(|<!|\bon\w+\s*=)", re.I)
URL_REF = re.compile(r"url\(\s*#([\w.-]+)\s*\)", re.I)
NUMBERISH = re.compile(r"^[\s\d.,+\-eE%a-zA-Z()#/:'\"_ ]*$")


class SvgRejected(ValueError):
    """The picture can't be accepted; the message tells Pip what to change."""


PIXELS_MIN, PIXELS_MAX, PALETTE_MAX = 4, 32, 16
HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def clean_pixels(rows, palette) -> tuple[list[str], dict]:
    """A pixel picture as Pip wrote it: rows of letters, each letter a colour from its palette, "." for nothing. Checked, never trusted."""
    if not isinstance(rows, list) or not all(isinstance(r, str) for r in rows):
        raise SvgRejected("`pixels` is a list of rows, each a string of palette letters (\".\" for nothing)")
    rows = [r.rstrip("\n") for r in rows]
    if not PIXELS_MIN <= len(rows) <= PIXELS_MAX:
        raise SvgRejected(f"a pixel picture is {PIXELS_MIN} to {PIXELS_MAX} rows tall; this one has {len(rows)}")
    width = len(rows[0])
    if not PIXELS_MIN <= width <= PIXELS_MAX or any(len(r) != width for r in rows):
        raise SvgRejected(f"every row needs the same length, {PIXELS_MIN} to {PIXELS_MAX} letters; check rows of a different length")
    if not isinstance(palette, dict) or not palette or len(palette) > PALETTE_MAX:
        raise SvgRejected(f"`palette` maps up to {PALETTE_MAX} single letters to colours like \"#3a2a1c\"")
    clean = {}
    for k, v in palette.items():
        if not (isinstance(k, str) and len(k) == 1 and k != "." and not k.isspace()) or not (isinstance(v, str) and HEX.match(v.strip())):
            raise SvgRejected(f"palette entry {k!r}: {v!r} isn't a single letter and a colour like \"#3a2a1c\"")
        clean[k] = v.strip().lower()
    unknown = sorted({ch for r in rows for ch in r if ch != "." and ch not in clean})
    if unknown:
        raise SvgRejected(f"these letters aren't in your palette: {' '.join(unknown)}")
    if all(ch == "." for r in rows for ch in r):
        raise SvgRejected("the picture is empty; put some colour in it")
    return rows, clean


def pixel_svg(rows: list[str], palette: dict) -> str:
    """The picture as crisp SVG on the usual canvas (one rect per run of a colour, scaled up whole and centred), so the gallery,
    postcards and looking all work as for any drawing."""
    h, w = len(rows), len(rows[0])
    k = min(CANVAS[0] // w, CANVAS[1] // h)
    out = [f'<svg xmlns="{SVG_NS}" viewBox="0 0 {CANVAS[0]} {CANVAS[1]}" width="{CANVAS[0]}" height="{CANVAS[1]}" shape-rendering="crispEdges">'
           f'<g transform="translate({(CANVAS[0] - w * k) // 2} {(CANVAS[1] - h * k) // 2}) scale({k})">']
    for y, row in enumerate(rows):
        x = 0
        while x < w:
            ch, start = row[x], x
            while x < w and row[x] == ch:
                x += 1
            if ch != ".":
                out.append(f'<rect x="{start}" y="{y}" width="{x - start}" height="1" fill="{palette[ch]}"/>')
    out.append("</g></svg>")
    return "".join(out)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def sanitize_svg(raw) -> str:
    """Return a safe, canonical SVG string or raise SvgRejected."""
    text = str(raw or "").strip()
    if not text:
        raise SvgRejected("the picture is empty")
    if len(text.encode()) > MAX_BYTES:
        raise SvgRejected(f"the picture is too big ({len(text.encode())} bytes; at most {MAX_BYTES}) - simplify it")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper() or "<?xml-stylesheet" in text.lower():
        raise SvgRejected("no DOCTYPE, entities or stylesheets: just the <svg> element")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise SvgRejected(f"that isn't valid SVG/XML ({e})") from None
    if _local(root.tag) != "svg":
        raise SvgRejected("the outermost element must be <svg>")
    count = 0
    ids: set[str] = set()
    refs: set[str] = set()

    def clean(el: ET.Element, depth: int) -> ET.Element:
        nonlocal count
        count += 1
        if count > MAX_ELEMENTS:
            raise SvgRejected(f"too many elements (at most {MAX_ELEMENTS}) - simplify it")
        if depth > MAX_DEPTH:
            raise SvgRejected(f"nested too deeply (at most {MAX_DEPTH} levels)")
        name = _local(el.tag)
        if name in FORBIDDEN_ELEMENTS or name not in ELEMENTS:
            raise SvgRejected(f"<{name}> isn't allowed here; use shapes, paths, text and gradients")
        out = ET.Element(name)
        for key, value in el.attrib.items():
            k = _local(key)
            v = str(value)
            if k.lower().startswith("on") or k in ("href", "style") or "href" in key.lower():
                raise SvgRejected(f"the attribute {k!r} isn't allowed (no scripts, links or styles)")
            if DANGEROUS.search(v):
                raise SvgRejected(f"the value of {k!r} contains something that isn't allowed")
            if k not in ATTRIBUTES or k in ("viewBox", "preserveAspectRatio") or (name == "svg" and k in ("width", "height")):
                continue  # unknown or canvas-defining attributes are simply dropped
            if len(v) > MAX_ATTR:
                raise SvgRejected(f"the {k!r} value is too long")
            for ref in URL_REF.findall(v):
                refs.add(ref)
            if "url(" in v.lower() and not URL_REF.search(v):
                raise SvgRejected("only url(#id) references to gradients in this picture are allowed")
            if k == "id":
                ids.add(v)
            out.set(k, v)
        if name in ("title", "desc", "text", "tspan"):
            out.text = clip(el.text or "", 400) if name != "text" and name != "tspan" else (el.text or "")[:400]
        for child in el:
            out.append(clean(child, depth + 1))
            if child.tail and name in ("text", "tspan"):
                out[-1].tail = child.tail[:400]
        return out

    svg = clean(root, 0)
    missing = refs - ids
    if missing:
        raise SvgRejected(f"it refers to gradients that don't exist: {', '.join(sorted(missing))}")
    svg.set("xmlns", SVG_NS)
    svg.set("viewBox", f"0 0 {CANVAS[0]} {CANVAS[1]}")
    svg.set("width", str(CANVAS[0]))
    svg.set("height", str(CANVAS[1]))
    return ET.tostring(svg, encoding="unicode")


def render_png(svg: str, width: int = 800) -> bytes:
    """Render a sanitised drawing to PNG (for a chat room). Raises ValueError if it can't be drawn."""
    import resvg_py
    return bytes(resvg_py.svg_to_bytes(svg_string=svg, width=width, background="#ffffff"))


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "picture"


def clean_title(raw) -> str:
    return clip(re.sub(r"\s+", " ", str(raw or "")).strip(), 80)


def clean_writing(raw) -> str:
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(raw or "")).strip()
    return text[:MAX_WRITING]


def pace(state, settings, now: float | None = None) -> str:
    """Why Pip can't finish another picture or piece of writing right now, or ''. Cheap in tokens, but a gallery of a
    hundred near-identical sketches isn't worth keeping, so there is a daily limit and a short gap."""
    import time
    from datetime import datetime
    now = now or time.time()
    day0 = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    today = state.works(limit=500, since=day0)
    if len(today) >= settings.works_per_day:
        return f"you've made as much as you can today ({settings.works_per_day}); come back to it tomorrow"
    if today and now - today[0]["ts"] < settings.works_min_gap_minutes * 60:
        wait = round((today[0]["ts"] + settings.works_min_gap_minutes * 60 - now) / 60) + 1
        return f"you only just finished something; give it about {wait} more minutes"
    return ""
