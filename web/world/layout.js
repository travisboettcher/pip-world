// A place built from parts (docs/DESIGN-modules.md, step 5): the engine sends the built shapes and anchors (app/layouts.py), and this draws them
// with the kit, the same way for every place. Rotations are in degrees, heading first (Euler order YXZ), so a part turned in a layout stays
// upright. Pip stands on the anchor tagged "pip" (and searches along it while gathering), people stand beside it ("people"), what can be
// found here lies on the anchor tagged "finds", and a shop's or market's goods are set out on the surface tagged "counter", its keeper behind.
import { goods, personAt, rngFor, tide, minutesNow } from "./templates/parts.js";
import { poseOf } from "./templates/home.js";

const SEASONAL = new Set(["grass", "cliff", "leaves"]);

export function build(kit, art, data) {
  const { THREE } = kit, T = art.T, season = data.now.season, lay = data.layout;
  let latest = data;
  kit.camera.position.set(0, 13, 22); kit.camera.lookAt(0, 0.2, -2);
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
  function material(m) {
    const o = { roughness: m.rough ?? 0.95, metalness: m.metal ?? 0 };
    if (m.color && !m.texture) o.color = new THREE.Color(m.color);
    if (m.emissive || m.lamp) { o.emissive = new THREE.Color(m.emissive || "#ffc070"); o.emissiveIntensity = m.lamp ? 0 : 1; }
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
      case "gable": { const g = new THREE.Shape(); g.moveTo(-s.width / 2, 0); g.lineTo(s.width / 2, 0); g.lineTo(0, s.height); g.closePath(); return new THREE.ShapeGeometry(g); }
    }
    return null;
  }
  const words = (t) => String(t || "").replace("$label", latest.place.label[0].toUpperCase() + latest.place.label.slice(1))
    .replace("$description", latest.place.description || latest.place.blurb || "").replace("$blurb", latest.place.blurb || "");
  const sway = [], moving = [];
  for (const s of lay.shapes) {
    let obj;
    if (s.hitbox) { obj = kit.hitbox(...s.size, ...s.at); if (s.rot) { obj.rotation.order = "YXZ"; obj.rotation.set(...s.rot.map((d) => (d * Math.PI) / 180)); } kit.tipOn(obj, () => ({ title: words(s.tip.title), text: words(s.tip.text) })); continue; }
    if (s.shape === "light") {
      obj = new THREE.PointLight(s.color, s.lamp ? 0 : s.strength, s.range, 2); obj.position.set(...s.at); kit.scene.add(obj);
      if (s.lamp) kit.lamp({ material: {} }, obj, s.strength);                // comes up at dusk
      continue;
    }
    if (s.shape === "sprite") {
      obj = kit.sprite(s.pixels ? art.picture(s.pixels) : art[s.art](), s.size[0], s.size[1], s.shadow !== false);
      obj.position.set(...s.at);
    } else {
      const mats = s.faces ? (() => { const top = material(s.faces.top), side = material(s.faces.side); return [side, side, top, side, side, side]; })() : material(s.material);
      obj = new THREE.Mesh(geometryOf(s), mats);
      obj.position.set(...s.at);
      obj.rotation.order = "YXZ";
      if (s.rot) obj.rotation.set(...s.rot.map((d) => (d * Math.PI) / 180));
      if (s.scale) obj.scale.set(...s.scale);
      obj.castShadow = s.shadow !== false; obj.receiveShadow = true;
      kit.scene.add(obj);
      const m = s.material || {};
      if (m.lamp) kit.lamp(obj, null, 1);
    }
    if (s.sway) { obj.userData.sway = sway.length * 0.7; sway.push(obj); }
    if (s.animate) moving.push({ obj, kind: s.animate, speed: s.speed, base: s.at[1] });
    if (s.tip) kit.tipOn(obj, () => ({ title: words(s.tip.title), text: words(s.tip.text) }));
  }
  if (sway.length) kit.every((t) => sway.forEach((m) => { m.rotation.z = Math.sin(t * 0.8 + m.userData.sway) * 0.025; }));
  if (moving.length) kit.every((t) => moving.forEach(({ obj, kind, speed, base }) => {     // water that flows; the sea, with the tide
    const map = (Array.isArray(obj.material) ? obj.material[0] : obj.material).map; if (map) map.offset.x = (t * speed) % 1;
    if (kind === "tide") obj.position.y = base - 0.1 + tide(minutesNow(latest)) * 0.5;
  }));

  // the living part: Pip, people, finds, on the anchors the layout says
  const tagged = (tag) => lay.anchors.find((a) => a.tags.includes(tag));
  const spot = tagged("pip") || lay.anchors.find((a) => a.type === "ground" || a.type === "floor") || { at: [0, 0, 0], extent: [4, 2] };
  const r = rngFor(data.place.key), findsAt = tagged("finds"), seat = tagged("seat");
  if (findsAt) (latest.place.finds || []).slice(0, 10).forEach((name, i) => {
    const [x, y, z] = findsAt.at, [w, d] = findsAt.extent;
    const g = goods(kit, name, /seed/.test(name) ? "seed" : /berr|apple|mushroom|nut/.test(name) ? "food" : "", x - w / 2 + ((i % 5) + 0.5) * (w / 5) + (r() - 0.5),
      y, z - d / 2 + (Math.floor(i / 5) + 0.5) * (d / 2) + (r() - 0.5), i);
    kit.tipOn(g, name, "Found here sometimes.");
  });
  // a shop's or market's goods, set out on the counter, with whoever keeps it standing behind
  const counter = tagged("counter");
  if (counter && data.booths?.length) {
    const b = data.booths[0], [x, y, z] = counter.at, [w] = counter.extent, items = b.items.slice(0, 6);
    items.forEach((it, i) => { const g = goods(kit, it.name, it.kind || "", x - w / 2 + ((i + 0.5) * w) / items.length, y, z, i); kit.tipOn(g, it.name, `${it.price} coin${it.price === 1 ? "" : "s"}${it.left ? "" : ", sold out"}.`); });
    const keeper = personAt(kit, art, b.look || { accessory: "apron" }, () => ({ title: b.whose || "The keeper", text: `Selling ${b.items.map((i) => i.name).join(", ")}.` }));
    keeper.stand(x, 0, z - 0.9);
  }
  const peopleAt = tagged("people") || spot;
  (data.present || []).slice(0, 4).forEach((c, i) => { const p = personAt(kit, art, c.look, () => ({ title: c.name, text: c.about || "" })); p.stand(peopleAt.at[0] + 2 + i * 1.2, peopleAt.at[1], peopleAt.at[2] - 0.6); });
  const pip = kit.sprite(art.pip(), 1.0, 1.375), spark = kit.sprite(art.spark(), 0.35, 0.35, false);
  kit.tipOn(pip, () => ({ title: "Pip", text: `${latest.pip.description || latest.pip.activity}.` }));
  kit.every((t) => {
    const pose = poseOf(latest.pip), [x, y, z] = spot.at, [w, d] = spot.extent;
    pip.visible = pose !== "away"; spark.visible = false;
    if (!pip.visible) return;
    if (pose === "gather") {                                         // searching back and forth across its spot, stopping now and then
      const k = (t * 0.03) % 1, stop = Math.floor(t / 2.5) % 2 === 0, px = x + Math.sin(k * Math.PI * 2) * w * 0.4, pz = z + Math.cos(k * Math.PI * 4) * d * 0.3;
      pip.position.set(px, y + 0.69, pz); kit.frame(pip, stop ? Math.floor(t * 1.6) % 2 : 2 + Math.floor(t * 8) % 4); pip.scale.x = Math.cos(k * Math.PI * 2) >= 0 ? 1 : -1;
      spark.visible = stop && Math.floor(t * 2) % 2 === 0; spark.position.set(px + 0.4, y + 0.3, pz + 0.2);
    } else if (pose === "sit" && seat) { pip.position.set(seat.at[0], seat.at[1] + 0.69, seat.at[2]); kit.frame(pip, 9); pip.scale.x = 1; }   // on the seat
    else { pip.position.set(x, y + 0.69, z); kit.frame(pip, Math.floor(t * 1.6) % 2); pip.scale.x = 1; }
  });
  return { update: (d) => { latest = d; } };
}
