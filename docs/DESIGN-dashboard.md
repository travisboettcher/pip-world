# Design: the engine's dashboard, with parts worlds reuse

Status (2026-11-17): built (0.58.0), deployed to Ashfall first; Pip's world gets it when it moves to the main line.

## Why
The engine audit (DESIGN-engine-audit.md, B5) made the dashboard a world pack's page: Pip's world has a full one (`worlds/pip/web/`, five
tabs), and a world without one gets the engine's plain page (the agent, its scene, what its modules show it, the last events). Ashfall
has no page of its own, so watching it, and now two agents in it, means reading databases by hand. Pip's page turns out to read nothing
but the engine's own endpoints; what ties it to Pip is the name written into its text, the "give" form's item kinds, and a few event
wordings. And no page shows a world of several agents as a whole.

## Decisions (the owner, 2026-11-17)
- **Pip's page, as parts.** It moves into the engine and becomes panels, one place each for the feed, chat, journal, map and scene,
  belongings, modules, the mind and the rest. A pack chooses its tabs and panels and may add panels of its own; Pip's world keeps its
  look and that choice. Every world gets the full dashboard; the plain page goes.
- **A view of the whole world**, beside the one-agent-at-a-time page (with its picker): everyone at a glance, what happens between
  them, and the world's own doings.
- **Ashfall first**, like every experimental build.

## How
- **Serving.** `/ui/` is the engine's dashboard (`web/dashboard/`) over the shared renderer (`web/world/`, three.js, fonts) as
  before; the pack's `web/` is served at `/ui/pack/`, so a pack adds but never replaces the engine's files.
- **A pack's say** (`web/dashboard.json`, all optional): `tabs` (each a `key`, `title` and its `panels` by name: the engine's or
  `pack:<file>` for one in the pack's `web/panels/`), `give` (extra fields per item kind for the owner's give form) and `items` (a
  line per item kind, from the item's attributes). `theme` names a stylesheet in its `web/` that restyles it. A pack with no `web/` gets the engine's own tabs.
- **No world in the engine's page.** Everything says the agent's name and pronoun from `/state` (`identity`), the stats the pack
  declares (`/state` `stats`: name, label, value, which way is good), its item kinds (`/state` `item_kinds`) and its home; the
  engine-neutral tests read the dashboard's files like the renderer's.
- **Several agents.** Every request carries `?agent=<key>` (the page's picker, kept in the URL). The **Everyone** tab, when there
  is more than one, shows each agent side by side (`GET /world/agents`: where, doing, mood, stats, condition, today's tokens: nothing
  of anyone's mind) and what happens between them (`GET /world/between`: meetings once each, what one said to another, letters and
  what was tucked in, and the post still on its way). **The world's doings** (`GET /world/doings`: the builder's nights with their
  reasons, modules going live, off or turned down, modules' failing calls by module, and people the world brought) is a panel in
  every world.
- None of the three is public (the public view's allowlist doesn't name them).

## Found while building
- Seen in a browser on a copy of Ashfall's data, the feed was empty: the newest 300 events of each agent were all `layout_built`.
  Each agent kept its own choice of a place's look (`scene:<key>`, which the model picks once), so the kind layouts (the ruins, the
  flats, the village) were built from Wren's look, then found stale and rebuilt from Ivo's, every beat: about 6,500 rebuilds a
  day per agent since 2026-11-15. A place's look is now the world's, kept by its first agent (`looks.keeper`); a start moves any look
  only another agent had into it (`looks.gather_scenes`). Pip's world, with one agent, never had it.
