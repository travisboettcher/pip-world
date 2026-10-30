# Design: Pip's pictures and writing

Status: **built 2026-10-30** (v1). Roadmap idea "Writing and drawing".

## What
Two tools that make something real Pip can show, as opposed to its private diary:
- **`draw(title, svg, caption?)`**: Pip writes a picture as SVG on a fixed 400 x 300 canvas.
- **`write_piece(title, text)`**: a poem, story or description (up to 2000 characters), public.

Both go into a **gallery** (table `works`, `GET /works`, the web UI's Work tab, `pipchat gallery`). A drawing can travel with a postcard
(`send_postcard(text, drawing=<id>)`) as a PNG on a channel that declares `images` (Matrix does). Pip sees its last few works by number in
its prompt, and they are searchable by `recall` and part of the nightly reflection like other events (`made_work`).

## Why SVG
It is text, so any model can write it with no image model or extra API, it is small, it stores and backs up trivially, and it scales. The
cost is that it is **untrusted text that reaches a browser and a chat room**, so it is never stored or served as written.

## Safety (the core of the design)
`art.sanitize_svg` parses with a strict whitelist and re-serialises on a fixed canvas:
- Allowed elements: svg, g, defs, rect, circle, ellipse, line, polyline, polygon, path, text, tspan, linear/radial gradients, stop, title, desc.
- Rejected with a reason Pip can act on: script, style, image, use, foreignObject, a, filters, masks, patterns, animation; any `on*`, `href`,
  `style` attribute; values containing `javascript:`, `data:`, `http(s):`, `//`; any `url()` that isn't a gradient defined in the same picture;
  DOCTYPE/entities/stylesheets; more than 400 elements, 12 levels, 24 KB, or any attribute over 4 KB.
- Unknown attributes are dropped; width, height and viewBox are forced to the canvas.
- Served only from what was stored: `/works/{id}.svg` carries `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; sandbox`
  and `nosniff`, and the UI shows it through `<img>` (which never runs scripts). A drawing that can't be rendered is refused at creation, not when someone looks.
- Pace: `WORKS_PER_DAY` (6) and a gap (`WORKS_MIN_GAP_MINUTES`, 10), so the gallery stays worth looking at.
- PNGs for chat are rendered by `resvg-py` (a self-contained renderer); the image installs DejaVu fonts so text draws.

## Not in v1
- **Pip looking at its own picture.** Pip knows only what it wrote. Letting it *see* a render needs image blocks in the LLM message format and
  backend; an obvious next step (draw, look, revise) and a good test of whether drawing improves with feedback.
- Drawing as a timed session with the dice (like work), colour/skill progression, a canvas Pip can continue over several sessions.
- Inbound pictures from the owner.
- Other media (music as notation, pixel art).
