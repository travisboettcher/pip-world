# Design: Pip's map

Status (2026-11-01): designed, not built. Owner idea: "a persistent map that grows as locations get added - something that could be the start of a
look into Pip's world, with a marker for where it is."

## Goal
A picture of Pip's world on the dashboard: home in the middle, every place Pip knows of around it, a marker where Pip is, and the marker
walking along the path while Pip travels. It only ever grows: a place keeps its spot once it has one. It is also the seed of a visual world
(ROADMAP M2b): the same layout can later carry sprites, weather and the garden.

## What the world gives us
Travel time to a place is a property of the destination (`Place.walk_minutes`, from `places.registry`), the same from anywhere. So the world is
a star around home, and the honest map is radial: a place's distance from home is its walking time. We do not invent a road network; each
place gets a short path from home. Places are: home, the library, the woods, the junkyard, each neighbor's home, and the invented places
(heard-of ones included: Pip has been told they exist, but not seen them).

## Layout: persistent coordinates
- A table `map_places(key PRIMARY KEY, x, y, placed_at)`. Home is the origin (0, 0), in minutes of walking per unit (so woods is ~8 units out).
- `worldmap.sync(state, settings, library)` gives every place in the registry that has no row yet a position and stores it. Existing rows are never
  moved, so a place keeps its spot even if its walk time later changes or other places come and go. A place removed from the registry
  (`DELETE /places/..`) is simply not shown; its row stays, so it returns to the same spot if it is re-added.
- New position: radius = the place's walking minutes (at least `MIN_RADIUS`), angle chosen from 24 candidates, starting at an offset from a hash
  of the key, as the one farthest from every point already placed (ties go to the first candidate). The hash makes the layout reproducible; the
  "farthest" rule keeps places from piling up. Sync runs in the monitor pass and on every `/map` request, so positions exist before anyone looks.

## Where Pip is
- At rest: the coordinates of `agent.location` (Pip's location is where it left from while walking, and where it is otherwise).
- Walking (a `walk` session): between the origin (`agent.location`) and the destination (`session.target`), by the session's elapsed fraction.
  The path is the straight line between the two points, which for a trip out from home is the spoke. `at` is null while walking.

## API
`GET /map` returns
```
{"home": "workshop",
 "places": [{"key", "label", "kind", "x", "y", "visited", "heard_only", "distance_minutes"}],
 "pip": {"x", "y", "at": <key or null>, "walking": {"from", "to", "progress"} | null}}
```
`kind` is `home`, `wild` (woods, junkyard), `library`, `neighbor`, or the invented place's own kind (`shop`, `sight`, ...). `visited` is whether Pip has
ever arrived (`state.last_arrived`), and `heard_only` marks an invented place Pip has been told of but not been to.

## Dashboard
A **Map** section in the World tab: an SVG that fits the places (viewBox from their extent plus margin), dotted spokes from home, a marker per place by
kind with its label, unvisited and heard-of places drawn faint, and Pip's marker (a pulsing dot, moving while walking). It refreshes every 5 seconds
while the tab is showing and on the `arrived` stream event. Pure SVG, no new library.

## Not now
Pairwise distances between places (travel is destination-based today), terrain, the garden and creations on the map, sprites and animation (M2b),
dragging places, and a text map for Matrix and `pipchat`.

## Tests
Placement (home at the origin, radius = minutes, never moves, picks the roomiest angle, reproducible), sync (adds only what is new, removed places
hidden but remembered), the snapshot (kinds, visited, heard-only, walking progress and its clamping), the `/map` endpoint, and a check that the
dashboard asset references the endpoint. The SVG drawing is checked by running its script against sample data in a headless browser.
