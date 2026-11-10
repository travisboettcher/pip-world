// Parts the place templates share: goods on a table, a dollhouse-cut building, trees, people. Everything is placed in kit (three.js) units.
import { hashStr } from "../art.js";

// A small thing for sale, shaped by what it is: coils of wire or line, gears, packets of seed, sacks of nuts, slabs of bark or driftwood,
// sea glass that catches the light, fruit and vegetables; anything else is a small crate.
export function goods(kit, name, kind, x, y, z, i = 0) {
  const T = kit.THREE, n = String(name).toLowerCase(), m = (c, o = {}) => kit.mat(null, { color: c, roughness: 0.6, ...o });
  const shaped = (geo, mat, dy) => { const o = kit.box(1, 1, 1, mat, x, y + dy, z); o.geometry = geo; return o; };
  if (/wire|line|rope|string|twine/.test(n)) { const o = shaped(new T.TorusGeometry(0.17, 0.06, 6, 10), m(/brass/.test(n) ? 0xc9a24a : /copper/.test(n) ? 0xb8703a : /line/.test(n) ? 0x7a9ab0 : 0x8a7a5a, { metalness: 0.5, roughness: 0.4 }), 0.1); o.rotation.x = Math.PI / 2; return o; }
  if (/gear|cog|spring|screw|bolt|nail/.test(n)) return shaped(new T.CylinderGeometry(0.18, 0.18, 0.06, 8), m(0xc9a24a, { metalness: 0.7, roughness: 0.3 }), 0.05);
  if (/file|awl|hammer|knife|chisel|saw|needle/.test(n)) return kit.box(0.5, 0.05, 0.08, m(0xb8b8b8, { metalness: 0.7 }), x, y + 0.03, z);
  if (kind === "seed" || /seed/.test(n)) return kit.box(0.22, 0.28, 0.06, m([0x7fb04f, 0xc8a048, 0xd88a4a][hashStr(n) % 3]), x, y + 0.14, z);
  if (/glass/.test(n)) { const c = [0x8fd8c8, 0x6fb88a, 0x4a78c8][i % 3]; return kit.box(0.12, 0.1, 0.12, m(c, { roughness: 0.15, emissive: c, emissiveIntensity: 0.15 }), x, y + 0.05, z); }
  if (/bark|wood|plank|stick|kindling/.test(n)) return kit.box(0.5, 0.1, 0.16, m(/drift|bleach/.test(n) ? 0xd8d0c0 : 0x5a3d27), x, y + 0.05, z);
  if (/nut|acorn|bean|pea|berr/.test(n)) return shaped(new T.SphereGeometry(0.2, 6, 5), m(0x9a6a3a), 0.18);
  if (kind === "food") { const o = shaped(new T.SphereGeometry(0.15, 6, 5), m([0xd8432f, 0xe0782a, 0x6fa047, 0xd8b24a][hashStr(n) % 4]), 0.14); return o; }
  return kit.box(0.25, 0.2, 0.25, m(0x8a6a4a), x, y + 0.1, z);
}

// A building opened like a dollhouse: floor, back and side walls, a back roof slope, gable ends, timber cut edges, an optional door gap
// in the right wall. Returns the spans so the caller can fill it.
export function cutaway(kit, art, { x0, x1, z0, z1, h = 3.2, wall = "plaster", roof = "thatch", door = true, doorTex }) {
  const { THREE } = kit, T = art.T, M = (t, o) => kit.mat(t, o), mid = (x0 + x1) / 2, zm = (z0 + z1) / 2;
  const outer = M(wall === "whitewash" ? T.whitewash([4, 2]) : wall === "stone" ? T.stone([4, 2]) : wall === "planks" ? T.planks([4, 2]) : wall === "brick" ? T.brick([4, 2]) : T.plaster([2, 1])), inner = M(T.inner([6, 2]));
  const floor = kit.boxTS(x1 - x0, 0.12, z1 - z0, M(T.floor([5, 3])), M(T.planks([5, 1], "#5a3d27")), mid, 0.06, zm);
  kit.box(x1 - x0, h, 0.3, [outer, outer, outer, outer, inner, outer], mid, h / 2, z0);
  kit.box(0.3, h, z1 - z0, [outer, inner, outer, outer, outer, outer], x0, h / 2, zm);
  if (door) {
    kit.box(0.3, h, 1.6, [outer, inner, outer, outer, outer, outer], x1, h / 2, z0 + 0.8); kit.box(0.3, h, (z1 - z0) - 3.5, [outer, inner, outer, outer, outer, outer], x1, h / 2, z1 - ((z1 - z0) - 3.5) / 2);
    kit.box(0.3, 0.9, 1.9, outer, x1, h - 0.45, z0 + 2.55);
  } else kit.box(0.3, h, z1 - z0, [outer, inner, outer, outer, outer, outer], x1, h / 2, zm);
  let doorMesh = null;
  if (door) { doorMesh = new THREE.Mesh(new THREE.PlaneGeometry(1.4, 2.1), M(doorTex || T.door(), { side: THREE.DoubleSide })); doorMesh.position.set(x1 + 0.55, 1.05, z0 + 2.0); doorMesh.rotation.y = -Math.PI / 2 + 0.85; kit.scene.add(doorMesh); }
  const fill = new THREE.PointLight(0xfff0dc, 0.9, (x1 - x0) * 1.3, 1.5); fill.position.set(mid, h * 0.8, z1 - 0.5); kit.scene.add(fill);   // daylight through the open side
  const timber = M(T.planks([1, 2], "#4a2f1f"));
  [x0, x1].forEach((x) => kit.box(0.4, h, 0.4, timber, x, h / 2, z1)); kit.box(x1 - x0 + 0.4, 0.3, 0.4, timber, mid, 0.15, z1);   // no top beam: it would cross the room at this angle
  const roofT = roof === "slate" ? T.slate([5, 2]) : roof === "shingle" ? T.shingles([5, 2]) : roof === "tile" ? T.tiles([5, 2]) : T.thatch([5, 2]);
  const r = kit.box(x1 - x0 + 1.1, 0.32, (z1 - z0) * 0.72, M(roofT), mid, h + (z1 - z0) * 0.2, z0 + (z1 - z0) * 0.22); r.rotation.x = -0.62;
  const gable = new THREE.Shape(); gable.moveTo(z0, 0); gable.lineTo(z1, 0); gable.lineTo(zm, (z1 - z0) * 0.42); gable.closePath();
  [x0 - 0.15, x1 + 0.15].forEach((x) => { const g = new THREE.Mesh(new THREE.ShapeGeometry(gable), M(wall === "whitewash" ? T.whitewash([2, 1]) : T.planks([2, 1], "#6b4529"), { side: THREE.DoubleSide })); g.rotation.y = -Math.PI / 2; g.position.set(x, h, 0); g.castShadow = true; kit.scene.add(g); });
  return { floor, door: doorMesh, mid, zm };
}

export function trees(kit, art, season, rng, { round = [], pines = [] }) {
  const { THREE } = kit, T = art.T, leaf = kit.mat(T.leaves([2, 2], season)), pine = kit.mat(T.leaves([2, 2], season, season === "winter" ? "#3f5a46" : "#2f6a3a")), trunk = kit.mat(T.planks([1, 2], "#5a3d27")), sway = [];
  for (const [x, z, s, y = 0] of round) {
    kit.box(0.5 * s, 1.6 * s, 0.5 * s, trunk, x, y + 0.8 * s, z);
    [[0, 2.4, 0, 1.5], [0.8, 2.0, 0.3, 1.0], [-0.8, 2.1, -0.2, 1.1], [0.2, 3.1, -0.3, 1.0]].forEach(([dx, dy, dz, r]) => { const m = kit.box(1, 1, 1, leaf, x + dx * s, y + dy * s, z + dz * s); m.geometry = new THREE.IcosahedronGeometry(r * s, 0); m.userData.sway = rng() * 6; sway.push(m); });
  }
  for (const [x, z, s, y = 0] of pines) { kit.box(0.3 * s, s, 0.3 * s, trunk, x, y + 0.5 * s, z); [[1.4, 1.6], [1.1, 2.5], [0.75, 3.3]].forEach(([r, h]) => { const m = kit.box(1, 1, 1, pine, x, y + h * s, z); m.geometry = new THREE.ConeGeometry(r * s, 1.4 * s, 7); }); }
  kit.every((t) => sway.forEach((m) => { m.rotation.z = Math.sin(t * 0.8 + m.userData.sway) * 0.025; }));
}

export function personAt(kit, art, look, tip) {           // a person sprite sized by their height, standing on y = 0 at the given spot
  const h = art.HEIGHT[look?.height] || art.HEIGHT.medium, s = kit.sprite(art.person(look), h * 12 / 26, h);
  s.userData.height = h; if (tip) kit.tipOn(s, tip);
  s.stand = (x, y, z) => s.position.set(x, y + h / 2, z);
  return s;
}

export const rngFor = (key) => { let s = hashStr(key) % 2147483647 || 1; return () => (s = (s * 16807) % 2147483647) / 2147483647; };
export const pipPose = (kit, pip, t, mode) => kit.frame(pip, mode === "walk" ? 2 + Math.floor(t * 8) % 4 : mode === "sit" ? 9 : mode === "sleep" ? 6 : Math.floor(t * 1.6) % 2);
export const minutesNow = (d) => (d.now.minutes + (Date.now() / 1000 - d.now.ts) / 60 + 1440) % 1440;
export const tide = (min) => 0.5 + 0.5 * Math.cos((min / 60 - 18) / 12.42 * Math.PI * 2);   // decoration only: high water near six

// What modules show (docs/DESIGN-modules.md): the server has already placed each object on an anchor, so this only draws it: a picture
// flat on a wall (facing the way the wall does), or standing up and facing the viewer on anything level. Kept by key, redrawn when it changes.
export function moduleObjects(kit, art) {
  const { THREE } = kit, shown = new Map(), motions = [];
  kit.every((t) => motions.forEach(({ mesh, motion, base, phase }) => {
    if (motion === "bob") mesh.position.y = base + Math.sin(t * 2 + phase) * 0.04;
    else if (motion === "sway") mesh.rotation.z = Math.sin(t * 1.3 + phase) * 0.08;
    else if (motion === "spin") mesh.scale.x = Math.cos(t * 1.5 + phase);
  }));
  function make(o) {
    const tex = o.frame ? art.framed(o) : art.picture(o);
    let mesh;
    if (o.upright) {
      mesh = kit.plane(o.w, o.h, kit.mat(tex, { transparent: true, alphaTest: 0.5 }), ...o.pos);
      mesh.rotation.y = Math.atan2(o.normal[0], o.normal[2]);
    } else { mesh = kit.sprite(tex, o.w, o.h, false); mesh.position.set(...o.pos); }
    if (o.tip) kit.tipOn(mesh, o.tip.title, o.tip.text);
    if (o.motion) motions.push({ mesh, motion: o.motion, base: o.pos[1], phase: hashStr(o.key) % 7 });
    return mesh;
  }
  function drop(key) {
    const old = shown.get(key); if (!old) return;
    kit.scene.remove(old.mesh); const i = kit.hits.indexOf(old.mesh); if (i >= 0) kit.hits.splice(i, 1);
    const j = motions.findIndex((m) => m.mesh === old.mesh); if (j >= 0) motions.splice(j, 1);
    shown.delete(key);
  }
  return {
    update(list) {
      const keep = new Set();
      for (const o of list) {
        const sig = JSON.stringify(o); keep.add(o.key);
        if (shown.get(o.key)?.sig === sig) continue;
        drop(o.key); shown.set(o.key, { sig, mesh: make(o) });
      }
      [...shown.keys()].filter((k) => !keep.has(k)).forEach(drop);
    },
  };
}

