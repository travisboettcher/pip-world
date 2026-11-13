// A place built from parts (docs/DESIGN-modules.md): the engine sends the built shapes and anchors (app/layouts.py), and this draws them with
// the kit, the same way for every place. Rotations are in degrees, heading first (Euler order YXZ), so a part turned in a layout stays upright.
// A shape with `when` shows only while its conditions hold (open, shut, day, night, the tide, the season, whether whoever lives here is home,
// whether Pip has set out a stall). What changes with the world is drawn on the anchors a layout tags for it:
//   pip, seat, bed, workbench, reading, garden-path, browse, visitor, pip-stall   where Pip stands, sits, sleeps, works, reads, gardens, browses
//   plot (in order)        a garden plot: its crop, growing         clock / shelf / walkers   Pip's creations: clocks, things, walking things
//   resident, resident-evening, resident-walk                       whoever lives here, by the time of day (a walk out at low tide)
//   people   others here     wares   what a neighbor sells     counter, stock   a shop's goods and keeper     booth   a market's booths
//   crowd    people walking about while it's open             finds   what can be found here, lying about
import { goods, personAt, rngFor, tide, minutesNow } from "./parts.js";
import { hashStr } from "./art.js";

const SEASONAL = new Set(["grass", "cliff", "leaves"]);
const WALKS = /\b(walk|walks|walker|legs?|crawl|hop|creature|toddle|scuttle)\b/i;
const GARDEN_WORDS = /garden|crop|plot|ripen|pea|tomato/i;
const SKINS = ["pale", "light", "olive", "brown", "dark"], HAIRS = ["white", "grey", "black", "brown", "auburn", "fair"];
const CLOTH = ["grey", "brown", "green", "blue", "red", "ochre", "plum", "cream"];
const hours = (min) => (min < 60 ? `${min} minutes` : `${Math.round(min / 60)} hours`);
const priced = (items) => items.map((i) => `${i.name} (${i.price} coin${i.price === 1 ? "" : "s"}${i.left ? "" : ", sold out"})`).join(", ");

export function poseOf(pip) {           // what Pip is doing, as a pose: the one place facts become animation
  if (!pip.here) return "away";
  if (pip.asleep) return "sleep";
  const s = pip.session, a = `${pip.activity} ${pip.description}`.toLowerCase();
  if (s && (s.kind === "work" || s.kind === "experiment")) return "work";
  if (s && s.kind === "read") return "read";
  if (s && s.kind === "gather") return "gather";
  if (s && s.kind === "module") {         // a module's session: work if it says so, else what the agent is doing (reading, gathering)
    if (s.working) return "work";
    if (pip.activity === "reading") return "read";
    if (pip.activity === "gathering") return "gather";
  }
  if (/\b(fil(e|es|ing)|tinker\w*|making|build\w*|hammer\w*|solder\w*|carv\w*|assembl\w*|shaping|sanding|measur\w*|cutting|fitting|winding)\b/.test(a) && !/\b(wait\w*|rest\w*)\b/.test(a)) return "work";
  if (/garden|plot|plant|harvest|water|weed|tend/.test(a) && !/wait|rest/.test(a)) return "garden";
  if (/wait|rest|sit|read|think|eat|bench/.test(a)) return "sit";
  return "idle";
}

export function build(kit, art, data) {
  const { THREE } = kit, T = art.T, season = data.now.season, lay = data.layout, r = rngFor(data.place.key);
  let latest = data;
  const cam = lay.camera || { at: [0, 13, 22], look: [0, 0.2, -2] };
  kit.camera.position.set(...cam.at); kit.camera.lookAt(...cam.look);

  // --- shapes ----------------------------------------------------------------------------------------------------------------
  const texCache = new Map();
  function texture(m) {
    const key = JSON.stringify([m.texture, m.repeat, m.color, m.color2]);
    if (texCache.has(key)) return texCache.get(key);
    const rep = m.repeat || [1, 1], n = m.texture;
    const t = n === "stripes" ? T.stripes(m.color || "#d8432f", m.color2 || "#f5f1d7") : n === "door" ? T.door() : n === "window" ? T.window(false)
      : n === "planks" ? T.planks(rep, m.color) : n === "leaves" ? T.leaves(rep, season, m.color) : SEASONAL.has(n) ? T[n](rep, season) : T[n](rep);
    texCache.set(key, t);
    return t;
  }
  const beams = [];
  function material(m) {
    if (m.beam) {                                                   // a faint light that shows only in the dark
      const b = new THREE.MeshBasicMaterial({ color: new THREE.Color(m.color || "#fff2c0"), transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide });
      beams.push(b); return b;
    }
    const o = { roughness: m.rough ?? 0.95, metalness: m.metal ?? 0 };
    if (m.color && !m.texture) o.color = new THREE.Color(m.color);
    if (m.emissive || m.lamp) { o.emissive = new THREE.Color(m.emissive || "#ffc070"); o.emissiveIntensity = m.lamp ? 0 : 1; }
    if (m.texture === "window" && m.lamp) o.emissiveMap = T.window(true);
    if (m.double) o.side = THREE.DoubleSide;
    if (m.opacity != null) { o.transparent = true; o.opacity = m.opacity; }
    return kit.mat(m.texture ? texture(m) : null, o);
  }
  function geometryOf(s) {
    switch (s.shape) {
      case "box": return new THREE.BoxGeometry(...s.size);
      case "plane": return new THREE.PlaneGeometry(...s.size);
      case "cylinder": return new THREE.CylinderGeometry(s.top, s.radius, s.height, s.segments);
      case "cone": return new THREE.ConeGeometry(s.radius, s.height, s.segments);
      case "sphere": return new THREE.SphereGeometry(s.radius, s.segments, Math.max(3, Math.round(s.segments * 0.75)));
      case "ico": return new THREE.IcosahedronGeometry(s.radius, 0);
      case "dodeca": return new THREE.DodecahedronGeometry(s.radius, 0);
      case "torus": return new THREE.TorusGeometry(s.radius, s.tube, 6, 12);
      case "gable": { const g = new THREE.Shape(); g.moveTo(-s.width / 2, 0); g.lineTo(s.width / 2, 0); g.lineTo(0, s.height); g.closePath(); return new THREE.ShapeGeometry(g); }
    }
    return null;
  }
  const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
  const words = (t) => String(t || "")
    .replace("$label", cap(latest.place.label)).replace("$description", latest.place.description || latest.place.blurb || "").replace("$blurb", latest.place.blurb || "")
    .replace("$belongings", (latest.items || []).map((i) => `${i.name} ×${i.qty}`).join(", ") + `; ${latest.coins ?? 0} coins.`)
    .replace("$project", latest.pip.session?.project ? `Pip is ${latest.pip.session.label || `busy with ${latest.pip.session.project}`}.` : "Where Pip works on its projects.")
    .replace("$hours", latest.place.hours ? `Open ${latest.place.hours[0]}:00 to ${latest.place.hours[1]}:00.` : "Shut for now.")
    .replace("$note", `At my stall in ${latest.lives_here?.away_at ?? "the market"} today.`)
    .replace("$resident", latest.lives_here?.name || "Someone")
    .replace("$wares", latest.lives_here?.wares?.length ? `For sale: ${latest.lives_here.wares.join(", ")}.` + (latest.lives_here.market_day ? ` Also at the market on ${latest.lives_here.market_day}s.` : "") : "Odds and ends, kept.")
    .replace("$stock", priced(latest.booths?.[0]?.items || []) ? `In stock: ${priced(latest.booths[0].items)}.` : "Bare shelves today.")
    .replace("$stall", latest.stall?.length ? `${latest.stall.map((s) => `${s.qty} ${s.item} at ${s.ask} coins`).join(", ")}.` : "Anyone can set out goods here.");
  const sway = [], moving = [], conditional = [];
  for (const s of lay.shapes) {
    let obj;
    if (s.hitbox) { obj = kit.hitbox(...s.size, ...s.at); if (s.rot) { obj.rotation.order = "YXZ"; obj.rotation.set(...s.rot.map((d) => (d * Math.PI) / 180)); } }
    else if (s.shape === "light") {
      obj = new THREE.PointLight(s.color, s.lamp ? 0 : s.strength, s.range, 2); obj.position.set(...s.at); kit.scene.add(obj);
      if (s.lamp) kit.lamp({ material: {} }, obj, s.strength);                // comes up at dusk
    } else if (s.shape === "sprite") {
      const tex = s.pixels ? art.picture(s.pixels) : s.art === "note" ? T.note() : s.art === "carrots" ? art.crop("carrot", 0.7) : art[s.art]();
      if (s.frame != null && tex.userData?.frames > 1) { const own = tex.clone(); own.needsUpdate = true; own.offset.x = s.frame / tex.userData.frames; obj = kit.sprite(own, s.size[0], s.size[1], s.shadow !== false); }
      else obj = kit.sprite(tex, s.size[0], s.size[1], s.shadow !== false);
      obj.position.set(...s.at);
    } else {
      const mats = s.faces ? (() => { const top = material(s.faces.top), side = material(s.faces.side); return [side, side, top, side, side, side]; })() : material(s.material);
      obj = new THREE.Mesh(geometryOf(s), mats);
      obj.position.set(...s.at);
      obj.rotation.order = "YXZ";
      if (s.rot) obj.rotation.set(...s.rot.map((d) => (d * Math.PI) / 180));
      if (s.scale) obj.scale.set(...s.scale);
      obj.castShadow = s.shadow !== false && !s.material?.beam; obj.receiveShadow = true;
      kit.scene.add(obj);
      const m = s.material || {};
      if (m.lamp) kit.lamp(obj, null, m.lamp === true ? 1 : m.lamp);
    }
    if (s.sway) { obj.userData.sway = sway.length * 0.7; sway.push(obj); }
    if (s.animate) moving.push({ obj, kind: s.animate, speed: s.speed, base: [...s.at], ph: (hashStr(JSON.stringify(s.at)) % 100) / 16 });
    if (s.when) conditional.push({ obj, when: s.when });
    if (s.tip) kit.tipOn(obj, () => ({ title: words(s.tip.title), text: words(s.tip.text) }));
  }
  if (sway.length) kit.every((t) => sway.forEach((m) => { m.rotation.z = Math.sin(t * 0.8 + m.userData.sway) * 0.025; }));
  if (moving.length) kit.every((t) => moving.forEach(({ obj, kind, speed, base, ph }) => {
    if (kind === "spin") { obj.rotation.y = t * speed; return; }
    if (kind === "wander") { obj.position.x = base[0] + Math.sin(t * speed * 10 + ph) * 0.6; const map = obj.material.map; if (map?.userData?.frames > 1) map.offset.x = (Math.floor(t * 2 + ph) % map.userData.frames) / map.userData.frames; return; }
    const map = (Array.isArray(obj.material) ? obj.material[0] : obj.material).map; if (map) map.offset.x = (t * speed) % 1;   // water that flows
    if (kind === "tide") obj.position.y = base[1] - 0.1 + tide(minutesNow(latest)) * 0.5;                                    // the sea, with the tide
  }));

  // --- conditions: what holds right now --------------------------------------------------------------------------------------
  function now() {
    const min = minutesNow(latest), open = !!latest.place.open, away = !!latest.lives_here?.away_at, high = tide(min) > 0.55, night = min < 6 * 60 || min >= 20 * 60;
    return { min, c: { open, shut: !open, day: !night, night, "high-tide": high, "low-tide": !high, winter: season === "winter", "not-winter": season !== "winter",
                       "resident-home": !!latest.lives_here && !away, "resident-away": away, "pip-stall": !!latest.stall?.length, "no-pip-stall": !latest.stall?.length,
                       ...Object.fromEntries(Array.from({ length: 8 }, (_, i) => [`booth-${i + 1}`, i < boothsUp])) } };
  }

  // --- anchors for what changes with the world -------------------------------------------------------------------------------
  const all = (tag) => lay.anchors.filter((a) => a.tags.includes(tag));
  const tagged = (tag) => all(tag)[0];
  const spot = tagged("pip") || lay.anchors.find((a) => a.type === "ground" || a.type === "floor") || { at: [0, 0, 0], extent: [4, 2] };
  const pick = (a) => a[Math.floor(r() * a.length)];
  const someone = (apron) => ({ height: pick(["short", "medium", "medium", "tall"]), hair: pick(HAIRS), skin: pick(SKINS), top: pick(CLOTH), bottom: pick(["grey", "brown", "navy", "black"]), accessory: apron ? "apron" : pick(["hat", "scarf", "satchel", "none", "none"]) });
  const along = (a, k) => [a.at[0] - a.extent[0] / 2 + k * a.extent[0], a.at[1], a.at[2]];
  const openOnly = [];                                              // things there only while the place is open

  // finds lying about
  const findsAt = tagged("finds");
  if (findsAt) (latest.place.finds || []).slice(0, 10).forEach((name, i) => {
    const [x, y, z] = findsAt.at, [w, d] = findsAt.extent;
    const g = goods(kit, name, /seed/.test(name) ? "seed" : /berr|apple|mushroom|nut/.test(name) ? "food" : "", x - w / 2 + ((i % 5) + 0.5) * (w / 5) + (r() - 0.5),
      y, z - d / 2 + (Math.floor(i / 5) + 0.5) * (d / 2) + (r() - 0.5), i);
    kit.tipOn(g, name, "Found here sometimes.");
  });

  // goods set out on a surface, spread along it
  function setOut(anchor, items, perItem = 1) {
    const [x, y, z] = anchor.at, [w] = anchor.extent, n = Math.max(1, items.length), made = [];
    items.forEach((it, i) => { for (let k = 0; k < perItem; k++) { const g = goods(kit, it.name || it.item, it.kind || "", x - w / 2 + ((i + 0.5) * w) / n + (k - (perItem - 1) / 2) * 0.16, y, z + (k % 2) * 0.25 - 0.1, k); made.push(g); } });
    return made;
  }
  // a shop: its goods on the counter and stock shelves, its keeper behind the counter while it's open
  const counter = tagged("counter"), booths = data.booths || [];
  if (counter && booths.length && !all("booth").length) {
    const b = booths[0];
    setOut(counter, b.items.slice(0, 4)).forEach((g) => kit.tipOn(g, () => ({ title: "The counter", text: priced(latest.booths[0]?.items || []) ? `In stock: ${priced(latest.booths[0]?.items || [])}.` : "Bare shelves today." })));
    all("stock").forEach((a, i) => setOut(a, b.items.slice(i * 3, i * 3 + 3)));
    const keeper = personAt(kit, art, b.look || data.present?.[0]?.look || someone(true), () => ({ title: b.whose || data.present?.[0]?.name || "The keeper", text: `Keeps ${latest.place.label}.` }));
    keeper.stand(counter.at[0], 0, counter.at[2] - 0.9); openOnly.push(keeper);
  }
  // a market: own booths in threes, then a character's stall each, on the booth anchors; a keeper behind each
  const boothAt = all("booth");
  let boothsUp = 0;
  if (boothAt.length) {
    const own = booths.filter((b) => !b.whose).flatMap((b) => { const g = []; for (let i = 0; i < b.items.length && g.length < 3; i += 3) g.push({ booth: b.booth, whose: "", items: b.items.slice(i, i + 3) }); return g; });
    [...own, ...booths.filter((b) => b.whose)].slice(0, boothAt.length).forEach((b, i) => {
      const a = boothAt[i]; boothsUp = i + 1;
      setOut(a, b.items, 3).forEach((g) => { kit.tipOn(g, b.whose ? `${b.whose}'s stall` : "A stall", `${priced(b.items)}. Prices move a little every day.`); openOnly.push(g); });
      const k = personAt(kit, art, b.whose ? b.look : someone(true), () => ({ title: b.whose || "A stallholder", text: `Selling ${priced(b.items)}.` }));
      k.stand(a.at[0] + 0.4, 0, a.at[2] - 1.0); openOnly.push(k);
    });
  }
  // Pip's own stall, with what it set out (its drawings and creations are shown by modules)
  const pipStallAt = tagged("pip-stall");
  let stallGoods = [];
  function showStall(stall) {
    stallGoods.forEach((g) => kit.scene.remove(g));
    stallGoods = pipStallAt ? setOut(pipStallAt, (stall || []).filter((s) => !["work", "creation"].includes(s.kind)).slice(0, 4), 3) : [];
  }
  // a neighbor's wares, on their shelves
  all("wares").forEach((a, i) => { const wares = (latest.lives_here?.wares || []).slice(i * 2, i * 2 + 2).map((name) => ({ name })); setOut(a, wares.length ? wares : (i === 0 && !latest.lives_here?.wares?.length ? [{ name: "jar" }, { name: "jar" }] : []), 2); });

  // the garden: each plot's crop, growing (what the garden module publishes: its plots, with when each was planted and ripens)
  const gardenOf = (d) => { const now = Date.now() / 1000;
    return (d.facts?.garden?.plots || []).map((p) => (p.crop ? { ...p, state: p.ready_at <= now ? "ready" : "growing", ready_in_min: Math.max(0, Math.ceil((p.ready_at - now) / 60)) }
                                                              : { plot: p.plot, state: "empty" })); };
  const plots = all("plot").map((a, i) => {
    const [x, y, z] = a.at, [w, d] = a.extent, sprites = [];   // y: the soil's middle
    const soil = kit.boxTS(w, 0.25, d, kit.mat(T.soil([1, 2])), kit.mat(T.planks([1, 1], "#5a3d27")), x, y, z); soil.visible = false;   // a plot the garden has
    const hit = kit.hitbox(w, 0.6, d, x, y + 0.3, z);
    kit.tipOn(hit, () => { const g = gardenOf(latest)[i]; if (!g || g.state === "empty") return { title: `Plot ${i + 1}`, text: "Empty, ready to plant." };
      return { title: `Plot ${g.plot}: ${g.crop}`, text: g.state === "ready" ? "Ripe now, ready to harvest." : `${Math.round(progress(g) * 100)}% grown; ripe in about ${hours(g.ready_in_min)}.` }; });
    for (let k = 0; k < 4; k++) { const s = kit.sprite(art.crop("x", 0), 0.9, 1.12); s.position.set(x - w * 0.21 + (k % 2) * w * 0.42, y + 0.66, z - d * 0.25 + Math.floor(k / 2) * d * 0.46); s.visible = false; sprites.push(s); }
    return { sprites, soil, hit, key: "" };
  });
  const progress = (g) => (g.ready_at > g.planted_at ? Math.max(0, Math.min(1, 1 - (g.ready_at - Date.now() / 1000) / (g.ready_at - g.planted_at))) : 1);
  function showGarden(garden) {
    plots.forEach((p, i) => {
      const g = (garden || [])[i], key = !g || g.state === "empty" ? "empty" : `${g.crop}|${g.state}|${Math.round(progress(g) * 10)}`;
      p.soil.visible = p.hit.visible = !!g;
      if (key === p.key) return; p.key = key;
      if (key === "empty") { p.sprites.forEach((s) => { s.visible = false; }); return; }
      const t = art.crop(g.crop, progress(g), g.state === "ready");
      p.sprites.forEach((s) => { s.visible = true; s.material.map = t; s.material.needsUpdate = true; s.customDepthMaterial.map = t; });
    });
  }

  // Pip's creations: a clock on the wall, things on the shelf, walking things on the floor
  const made = new Map(), clocks = all("clock"), shelf = tagged("shelf"), walkersAt = tagged("walkers");
  const fit = (p, most) => { const w = p.rows[0].length, h = p.rows.length, k = most / Math.max(w, h); return [w * k, h * k]; };
  function showCreations(list) {
    let wall = 0, floor = 0, onShelf = 0;
    for (const c of list || []) {
      const pk = c.picture ? JSON.stringify(c.picture) : "";
      if (made.has(c.name) && made.get(c.name).pk === pk) { const e = made.get(c.name); if (e.kind === "clock") wall++; else if (e.kind === "walker") floor++; else onShelf++; continue; }
      if (made.has(c.name)) { const old = made.get(c.name); kit.scene.remove(old.mesh); kit.hits.splice(kit.hits.indexOf(old.mesh), 1); made.delete(c.name); }
      let e = null;
      if (c.clock && clocks[wall]) { const ck = art.clock(), a = clocks[wall++]; const m = kit.sprite(ck.texture, 0.85, 1.5, false); m.quaternion.identity(); m.position.set(a.at[0], a.at[1], a.at[2] + 0.05); e = { mesh: m, kind: "clock", ck }; }
      else if ((WALKS.test(c.description) || c.capabilities.includes("companion")) && walkersAt) { const t = c.picture ? art.picture(c.picture) : art.walker(), [w, h] = c.picture ? fit(c.picture, 0.8) : [0.8, 0.57]; e = { mesh: kit.sprite(t, w, h), kind: "walker", t, lane: floor++ }; }
      else if (shelf) { const [w, h] = c.picture ? fit(c.picture, 0.5) : [0.5, 0.5], m = kit.sprite(c.picture ? art.picture(c.picture) : art.contraption(c.quality, hashStr(c.name)), w, h, false); m.position.set(shelf.at[0] - shelf.extent[0] / 2 + 0.3 + onShelf * 0.55, shelf.at[1] + h / 2, shelf.at[2]); onShelf++; e = { mesh: m, kind: "thing" }; }
      if (!e) continue;
      kit.tipOn(e.mesh, () => { const n = latest.creations.find((x) => x.name === c.name) || c; return { title: n.name, text: `${n.quality}. ${n.description}` + (n.clock ? (n.clock.running ? " It's going." : " It has stopped and needs tending.") : "") }; });
      e.name = c.name; e.pk = pk; made.set(c.name, e);
    }
    for (const [name, e] of made) e.mesh.visible = (list || []).some((c) => c.name === name);     // sold or given away: gone
  }

  // people: whoever lives here, anyone else here, a crowd while it's open
  const lives = latest.lives_here, resident = lives && tagged("resident") ? personAt(kit, art, lives.look, () => ({ title: lives.name, text: lives.about || "" })) : null;
  const others = [], peopleAt = tagged("people") || spot;
  function showPeople(present) {
    others.forEach((o) => { o.visible = false; });
    (present || []).filter((p) => p.name !== lives?.name).slice(0, 4).forEach((p, i) => {
      others[i] ??= personAt(kit, art, p.look, () => ({ title: p.name, text: p.about || "" }));
      others[i].visible = true; others[i].stand(peopleAt.at[0] + 2 + i * 1.2, peopleAt.at[1], peopleAt.at[2] - 0.6);
    });
  }
  const crowdAt = tagged("crowd");
  const crowd = crowdAt ? Array.from({ length: 8 }, (_, i) => { const p = personAt(kit, art, someone(false), () => ({ title: "Someone about", text: `Here for ${latest.place.label}.` })); p.userData.k = i / 8; p.userData.speed = 0.012 + r() * 0.01; p.userData.lane = (r() - 0.5) * 1.2; return p; }) : [];

  // Pip, and what goes with a pose: a thought, sleep, sparks, a book
  const pip = kit.sprite(art.pip(), 1.0, 1.375), spark = kit.sprite(art.spark(), 0.35, 0.35, false), zzz = kit.sprite(art.zzz(), 0.6, 0.6, false);
  const bubble = kit.sprite(art.bubble(), 0.7, 0.6, false), book = kit.sprite(art.bubble("#8a3a2a"), 0.5, 0.42, false);
  kit.tipOn(pip, () => ({ title: "Pip", text: `${latest.pip.description || latest.pip.activity}.` + (latest.pip.mood ? ` Feeling ${latest.pip.mood}; energy ${Math.round((latest.pip.energy ?? 0) * 100)}%.` : "") }));
  const seat = tagged("seat"), bed = tagged("bed") || seat, bench = tagged("workbench"), reading = tagged("reading") || seat, gardenPath = tagged("garden-path"),
    browse = tagged("browse"), visitor = tagged("visitor");

  function update(d) {
    latest = d; showGarden(gardenOf(d)); showCreations(d.creations); showPeople(d.present); showStall(d.stall);
    const ripe = gardenOf(d).find((g) => g.state !== "empty");
    bubble.material.map = art.bubble(ripe && /tomato/i.test(ripe.crop) ? "#d8432f" : "#6aa847");
  }
  update(data);

  kit.every((t) => {
    const { min, c } = now();
    for (const { obj, when } of conditional) obj.visible = when.every((w) => c[w]);
    for (const b of beams) b.opacity = (kit.dark || 0) * 0.16;
    for (const o of openOnly) o.visible = c.open;
    stallGoods.forEach((g) => { g.visible = c.open; });
    crowd.forEach((p, i) => { p.visible = c.open; if (!c.open) return; const k = (p.userData.k + t * p.userData.speed) % 1, a = crowdAt;
      const x = a.at[0] + Math.cos(k * Math.PI * 2) * a.extent[0] / 2 + p.userData.lane, z = a.at[2] + Math.sin(k * Math.PI * 2) * a.extent[1] / 2 + p.userData.lane * 0.6;
      p.stand(x, a.at[1], z); p.scale.x = Math.sin(k * Math.PI * 2) >= 0 ? -1 : 1; kit.frame(p, 2 + Math.floor(t * 6 + i) % 4); });
    // whoever lives here: away at the market, asleep at night, walking out at a morning low tide, at the table in the evening, else about the house
    if (resident) {
      const away = c["resident-away"], asleep = min >= 23 * 60 || min < 6 * 60, walk = tagged("resident-walk"), evening = tagged("resident-evening");
      resident.visible = !away && !asleep;
      if (resident.visible) {
        if (walk && min < 9 * 60 && c["low-tide"]) { const k = (Math.sin(t * 0.15) + 1) / 2, [x, y, z] = along(walk, k); resident.stand(x, y, z + Math.sin(t * 0.3) * walk.extent[1] / 2); kit.frame(resident, 2 + Math.floor(t * 4) % 4); }
        else if (evening && min >= 20 * 60) { resident.stand(...evening.at); kit.frame(resident, Math.floor(t * 1.2) % 2); }
        else { resident.stand(...tagged("resident").at); kit.frame(resident, Math.floor(t * 1.2) % 2); }
      }
    }
    others.forEach((o, i) => { if (o.visible) kit.frame(o, Math.floor(t * 1.1 + i) % 2); });
    // creations that move: a clock's hands, walking things
    for (const e of made.values()) {
      if (e.kind === "clock") { const cr = latest.creations.find((x) => x.name === e.name) || {}; const m = cr.clock ? cr.clock.minutes + (cr.clock.running ? (Date.now() / 1000 - latest.now.ts) / 60 : 0) : 0; e.ck.draw(Math.floor(m), cr.clock?.running ? Math.round(Math.sin(t * Math.PI) * 2) : 0); }
      if (e.kind === "walker") { const k = (Math.sin(t * 0.35 + e.lane) + 1) / 2, [x, y, z] = along(walkersAt, k); e.mesh.position.set(x, y + 0.3, z + walkersAt.extent[1] / 2 - 0.3 - e.lane * 0.6); e.mesh.scale.x = Math.cos(t * 0.35 + e.lane) >= 0 ? 1 : -1; if (e.t.userData.frames > 1) e.t.offset.x = (Math.floor(t * 6) % 2) / 2; }
    }
    // Pip
    const pose = poseOf(latest.pip), at = (a, frame, dy = 0.69) => { pip.position.set(a.at[0], a.at[1] + dy, a.at[2]); kit.frame(pip, frame); };
    pip.visible = pose !== "away"; spark.visible = zzz.visible = bubble.visible = book.visible = false; pip.scale.x = 1;
    if (!pip.visible) return;
    const [x, y, z] = spot.at, [w, d] = spot.extent;
    if (pose === "gather") {                                         // searching back and forth across its spot, stopping now and then
      const k = (t * 0.03) % 1, stop = Math.floor(t / 2.5) % 2 === 0, px = x + Math.sin(k * Math.PI * 2) * w * 0.4, pz = z + Math.cos(k * Math.PI * 4) * d * 0.3;
      pip.position.set(px, y + 0.69, pz); kit.frame(pip, stop ? Math.floor(t * 1.6) % 2 : 2 + Math.floor(t * 8) % 4); pip.scale.x = Math.cos(k * Math.PI * 2) >= 0 ? 1 : -1;
      spark.visible = stop && Math.floor(t * 2) % 2 === 0; spark.position.set(px + 0.4, y + 0.3, pz + 0.2);
    } else if (pose === "sleep" && bed) { at(bed, 6); zzz.visible = true; zzz.position.set(bed.at[0] + 0.6, bed.at[1] + 1.6 + ((t * 0.3) % 0.4), bed.at[2] + 0.05); }
    else if (pose === "sit" && seat) { at(seat, 9); bubble.visible = GARDEN_WORDS.test(latest.pip.description || "") && plots.length > 0 && Math.floor(t / 3) % 3 !== 2; bubble.position.set(seat.at[0] + 0.5, seat.at[1] + 1.8 + Math.sin(t * 2) * 0.04, seat.at[2] + 0.05); }
    else if (pose === "read" && reading) { at(reading, 9); book.visible = true; book.position.set(reading.at[0] + 0.5, reading.at[1] + 1.6 + Math.sin(t * 2) * 0.03, reading.at[2] + 0.1); }
    else if (pose === "work" && bench) { const hit = Math.floor(t * 4) % 2; at(bench, 7 + hit); spark.visible = hit === 1; spark.position.set(bench.at[0] + 0.7, bench.at[1] + 1.49, bench.at[2] - 0.65); }
    else if (pose === "garden" && gardenPath) { const k = (t * 0.05) % 1, still = k > 0.3 && k < 0.5, [gx, gy, gz] = along(gardenPath, k < 0.5 ? k * 2 : 2 - k * 2); pip.position.set(gx, gy + 0.69, gz); kit.frame(pip, still ? Math.floor(t * 1.6) % 2 : 2 + Math.floor(t * 8) % 4); pip.scale.x = k > 0.5 ? -1 : 1; }
    else if (c["pip-stall"] && pipStallAt) { pip.position.set(pipStallAt.at[0] + 0.4, 0.69, pipStallAt.at[2] - 1.1); kit.frame(pip, Math.floor(t * 1.6) % 2); }
    else if (browse) { const k = (Math.sin(t * 0.25) + 1) / 2, [bx, by, bz] = along(browse, k); pip.position.set(bx, by + 0.69, bz); kit.frame(pip, Math.abs(Math.cos(t * 0.25)) > 0.2 ? 2 + Math.floor(t * 8) % 4 : Math.floor(t * 1.6) % 2); pip.scale.x = Math.cos(t * 0.25) >= 0 ? 1 : -1; }
    else if (visitor && resident?.visible) at(visitor, Math.floor(t * 1.6) % 2);
    else { pip.position.set(x, y + 0.69, z); kit.frame(pip, pose === "sleep" ? 6 : Math.floor(t * 1.6) % 2); }
  });
  return { update };
}
