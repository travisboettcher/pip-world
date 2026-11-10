# Design: Pip's pictures and writing

Status: **built 2026-10-30** (v1); **pixel drawing, occasions and drawings in the world built 2026-11-09 (0.16.0)**. Roadmap idea "Writing and drawing".

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
- Drawing as a timed session with the dice (like work), colour/skill progression, a canvas Pip can continue over several sessions.
- Inbound pictures from the owner.
- Other media (music as notation, pixel art).

## Pip sees its pictures (built 2026-10-30)
A tool result can carry pictures: the neutral message format gains `images` on a result, the Anthropic backend sends them as image blocks inside the
`tool_result`, and an OpenAI-compatible backend sends them as a user message right after the tool messages (only if `LLM_VISION=1`). Pictures are only ever
rendered by the engine from sanitised SVG (480 px wide, a few hundred tokens), live for the turn, and are never stored in events. `draw` returns the render and
asks whether to redo it; `draw(replaces=<id>)` redraws in place (3 times at most, not held back by the gap between new pictures); `look(drawing)` shows any
drawing again (`LOOKS_PER_DAY`, 20). A backend without vision is never sent a picture, and `look` isn't offered.

## Pixel drawing, occasions, and drawings in the world (built 2026-11-09, 0.16.0)
Pip had `draw` for ten days and made nothing: a whole SVG document is a lot to write, and nothing ever said when a picture was worth making.
Three changes, together:

**Pixel art.** `draw` also takes `pixels` (4 to 32 rows, all the same length, 4 to 32 letters) and `palette` (up to 16 single letters, each
`#rgb` or `#rrggbb`; `.` is nothing). `art.clean_pixels` checks it and every refusal says what to fix (rows of different lengths, letters
missing from the palette, an empty picture). `art.pixel_svg` turns it into SVG on the usual 400 x 300 canvas: one `rect` per run of a colour
in a group scaled up by a whole number and centred, `shape-rendering="crispEdges"` (now on the allowlist), and the result still goes through
`sanitize_svg`, so the gallery, postcards and `look` work unchanged. The grid itself is kept (`works.pixels`, JSON) for the world view. SVG
still works for anything pixels can't say.

**Occasions, as facts.** The tool description and the guide name when a picture is worth making: a sketch of something being designed, a
place seen for the first time, something that happened, a picture for a friend. Short facts appear only where `draw` is a tool:
`start_project`'s result ends "You could sketch it first with draw."; free time adds "draw makes a picture; a small pixel one is quick.";
in recent events a first arrival says "(draw can keep a picture of it)" and a finished creation says a drawing of it `of="<name>"` becomes how
it looks. None of these are orders and none repeat beyond the event that prompts them.

**Drawings in the world.** (Since 0.18.0 the wall and the stall are the `gallery-wall` and `stall-pictures` modules; see
DESIGN-modules.md, step 2.) `draw(of=<creation>)` records the picture's subject (`works.subject`; `replaces` keeps it). In the world view
(DESIGN-world-view.md) the workshop hangs the three newest pixel drawings framed on the back wall (`drawings` in the home scene); a creation
with a pixel picture is drawn as that picture instead of the generic contraption or walker (clocks keep their working face); and on a
stall, copies of a pixel drawing stand framed and propped up, and a creation Pip drew stands as its picture (`picture` on stall lines).
SVG drawings have no grid, so they stay in the gallery only.

Measure: drawings per week before (zero in ten days) and after; which occasions they follow.

