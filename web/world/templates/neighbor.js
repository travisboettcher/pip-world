// A neighbor's home (docs/DESIGN-world-view.md): their cottage opened like a dollhouse, with what they sell on show and the details their
// record gives (a lighthouse, a tide chart, a tin by the door...). By the water it stands on a marsh above mudflats the tide covers and
// uncovers; inland, on a terrace in a meadow. They are home, out at the market on their day, or asleep at night.
import { goods, cutaway, trees, personAt, rngFor, minutesNow, tide } from "./parts.js";
import { poseOf } from "./home.js";

const CX0 = -5, CX1 = 3.5, CZ0 = -9.5, CZ1 = -4.4;

export function build(kit, art, data) {
  const { THREE } = kit, T = art.T, M = (t, o) => kit.mat(t, o), season = data.now.season, P = new Set(data.place.props), coastal = data.place.coastal;
  const r = rngFor(data.place.key), who = data.lives_here || { name: "Someone", about: "", look: {}, wares: [] };
  let latest = data;
  kit.camera.position.set(0, 13, 19); kit.camera.lookAt(0, 0.2, -4.6);
  // the land
  if (coastal) {
    kit.boxTS(26, 1.2, 15, M(T.marsh([13, 8])), M(T.cliff([13, 1], season)), 6, -0.6, -3.5);
    kit.boxTS(22, 0.6, 30, M(T.mud([11, 15])), M(T.mud([11, 1])), -18, -0.85, -5);
    kit.boxTS(40, 1, 14, M(T.marsh([20, 7])), M(T.mud([20, 1])), 6, -1.6, 10);                       // the low marsh in front
    const seaMat = M(T.sea([18, 20]), { roughness: 0.25, transparent: true, opacity: 0.88 }), sea = kit.box(40, 1, 40, seaMat, -26, -1.2, -6); sea.castShadow = false;
    kit.tipOn(sea, "The sea", "It comes in over the mudflats and goes out again.");
    kit.every((t) => { sea.position.y = -1.32 + tide(minutesNow(latest)) * 0.55; seaMat.map.offset.x = (t * 0.01) % 1; });
    if (P.has("shingle")) { const sh = kit.boxTS(14, 0.9, 3.5, M(T.pebbles([7, 2])), M(T.pebbles([7, 1])), -9.5, -0.35, -11.5); sh.rotation.y = 0.12; kit.tipOn(sh, "The shingle bank", "It grows overnight, and moves the paths along the shore."); for (let g = 0; g < 3; g++) for (let i = 0; i < 9; i++) kit.box(0.25, 1.4 + (i % 2) * 0.2, 0.25, M(T.planks([1, 1], "#3f3326")), -13.5 + g * 3.2 - i * 0.55, -0.4, -9.5 + i * 0.9); }
    const reed = art.reed(); for (let i = 0; i < (P.has("reeds") ? 60 : 25); i++) { const s = kit.sprite(reed, 0.5, 1.0, false); const left = i < 34; s.position.set(left ? -6.8 + r() * 1.6 : -4 + r() * 22, left ? -0.1 : 0.45, left ? -10 + r() * 14 : 2.4 + r() * 1.6); }
    if (P.has("birds")) { const bird = art.curlew(), birds = []; for (let i = 0; i < 9; i++) { const b = kit.sprite(bird, 0.6, 0.48); b.userData.home = [-15 + r() * 7, -3 + r() * 6]; b.userData.ph = r() * 6; birds.push(b); kit.tipOn(b, "A curlew", "Feeding on the flats while the tide is out."); }
      kit.every((t) => { const hi = tide(minutesNow(latest)) > 0.55; birds.forEach((b, i) => { const [hx, hz] = b.userData.home; b.position.set(hi ? -12 + i * 0.6 : hx + Math.sin(t * 0.2 + b.userData.ph) * 0.6, hi ? 0.4 : -0.31, hi ? -10.3 - (i % 3) * 0.4 : hz); }); bird.offset.x = (Math.floor(t * 2) % 2) / 2; }); }
  } else {
    kit.boxTS(30, 2, 16, M(T.grass([15, 8], season)), M(T.cliff([15, 1], season)), 0, -1, -4);
    kit.boxTS(40, 1, 12, M(T.grass([20, 6], season)), M(T.cliff([20, 1], season)), 0, -2.5, 9);
    trees(kit, art, season, r, { round: [[10.5, -6, 1.1], [-9, -8.5, 0.9]], pines: Array.from({ length: 12 }, (_, i) => [-15 + i * 2.6 + r(), -12.5 - r() * 2, 1.2 + r() * 0.7]) });
    if (P.has("beehives")) for (let i = 0; i < 3; i++) kit.tipOn(kit.box(0.7, 0.9, 0.7, M(T.planks([1, 1], "#d8c08a")), 7 + i * 1.3, 0.45, -7.5), "A beehive", "Humming, on a warm day.");
  }
  if (P.has("lighthouse")) {
    kit.boxTS(4, 1.6, 4, M(T.stone([2, 1])), M(T.stone([2, 1])), -11, -0.2, -16);
    const tower = kit.box(1, 1, 1, M(T.whitewash([3, 4])), -11, 4.1, -16); tower.geometry = new THREE.CylinderGeometry(0.85, 1.15, 7, 10);
    const band = kit.box(1, 1, 1, M(null, { color: 0xb5402f }), -11, 5.4, -16); band.geometry = new THREE.CylinderGeometry(0.93, 0.96, 0.8, 10);
    const lampMat = new THREE.MeshStandardMaterial({ color: 0x444036, emissive: 0xfff0b0, emissiveIntensity: 0 }), lamp = kit.box(1, 1, 1, lampMat, -11, 8.0, -16); lamp.geometry = new THREE.CylinderGeometry(0.7, 0.7, 0.9, 10); kit.lamp(lamp, null, 1.3);
    const cap = kit.box(1, 1, 1, M(null, { color: 0x2f3a3e }), -11, 8.8, -16); cap.geometry = new THREE.ConeGeometry(0.95, 0.8, 10);
    kit.tipOn(tower, "The lighthouse", "It stands over the water on its rock.");
    const beamMat = new THREE.MeshBasicMaterial({ color: 0xfff2c0, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide });
    const beam = new THREE.Mesh(new THREE.PlaneGeometry(14, 1.1), beamMat); beam.position.set(-11, 8.0, -16); kit.scene.add(beam);
    kit.every((t) => { beam.rotation.y = t * 0.6; beamMat.opacity = (kit.dark || 0) * 0.16; });
  }
  // the cottage
  const sc = data.place.scene || {};
  const c = cutaway(kit, art, { x0: CX0, x1: CX1, z0: CZ0, z1: CZ1, h: 3.0, wall: sc.walls || (coastal ? "whitewash" : "plaster"), roof: sc.roof || (coastal ? "slate" : "thatch") });
  kit.tipOn(c.floor, () => ({ title: `${who.name}'s home`, text: who.about || "" }));
  kit.box(0.7, 2.2, 0.7, M(T.stone([1, 2])), CX0 + 1.2, 4.4, CZ0 + 0.5);
  const win = M(T.window(false), { emissive: 0xffb050, emissiveMap: T.window(true), emissiveIntensity: 0 });
  const winMesh = kit.plane(1.2, 1.2, win, -1.6, 1.9, CZ0 + 0.21); kit.tipOn(winMesh, "The window", coastal ? "It faces the water." : "It looks out on the garden.");
  const roomLight = new THREE.PointLight(0xffb066, 0, 8, 2); roomLight.position.set(0.5, 2.2, -6.0); kit.scene.add(roomLight);
  const homeLamp = { mesh: winMesh, light: roomLight, strength: 1 }; kit.lamps.push(homeLamp);
  // what they sell, on a cabinet's shelves
  const cab = M(T.planks([2, 2], "#6b4a30"));
  kit.box(2.6, 2.4, 0.6, cab, -3.4, 1.2, CZ0 + 0.55);
  for (let shelf = 0; shelf < 3; shelf++) kit.box(2.4, 0.06, 0.55, cab, -3.4, 0.55 + shelf * 0.7, CZ0 + 0.85);
  (who.wares.length ? who.wares : ["jar", "jar", "jar"]).slice(0, 6).forEach((w, i) => { for (let k = 0; k < 2; k++) goods(kit, w, "", -4.3 + (i % 2) * 1.0 + k * 0.4, 0.58 + Math.floor(i / 2) * 0.7, CZ0 + 0.9, k); });
  const cabTip = kit.hitbox(2.6, 2.4, 0.9, -3.4, 1.2, CZ0 + 0.9);
  kit.tipOn(cabTip, () => ({ title: `${who.name}'s cabinet`, text: who.wares.length ? `For sale: ${who.wares.join(", ")}.` + (who.market_day ? ` Also at the market on ${who.market_day}s.` : "") : "Odds and ends, kept." }));
  // table, chair, stove, and the record's own details
  const table = kit.box(1.8, 0.12, 1.1, M(T.planks([2, 1], "#8a6440")), 0.2, 0.85, -6.6); [[-0.75, -0.45], [0.75, -0.45], [-0.75, 0.45], [0.75, 0.45]].forEach(([dx, dz]) => kit.box(0.12, 0.8, 0.12, cab, 0.2 + dx, 0.4, -6.6 + dz));
  if (P.has("books")) { const b = new THREE.Mesh(new THREE.PlaneGeometry(0.8, 0.5), M(T.book())); b.rotation.x = -Math.PI / 2; b.position.set(0.0, 0.92, -6.5); kit.scene.add(b); kit.tipOn(table, "The table", "An open book, kept up every day."); }
  const stoveMat = new THREE.MeshStandardMaterial({ color: 0x2a2624, emissive: 0xff8a3a, emissiveIntensity: 0, roughness: 0.6 });
  kit.box(1.0, 1.0, 0.8, M(null, { color: 0x2f2c2a, roughness: 0.6, metalness: 0.3 }), 2.6, 0.55, CZ0 + 0.7); const slot = kit.box(0.5, 0.2, 0.05, stoveMat, 2.6, 0.5, CZ0 + 1.12); kit.box(0.18, 1.6, 0.18, M(null, { color: 0x2f2c2a }), 2.6, 1.85, CZ0 + 0.6);
  kit.lamps.push({ mesh: slot, light: null, strength: 0.8 });
  if (P.has("tide chart")) kit.tipOn(kit.plane(1.3, 0.8, M(T.chart()), 0.6, 2.1, CZ0 + 0.21), "A tide chart", "High and low water, marked by hand.");
  if (P.has("tin")) { const tin = kit.box(1, 1, 1, M(null, { color: 0xc9a24a, metalness: 0.6, roughness: 0.4 }), CX1 - 0.6, 0.3, CZ0 + 2.9); tin.geometry = new THREE.CylinderGeometry(0.22, 0.22, 0.36, 10); kit.tipOn(tin, "A tin by the door", "Something kept, by the door."); }
  const stone = M(T.stone([1, 1])), step = kit.boxTS(1.4, 0.25, 1.4, stone, stone, CX1 + 1.0, 0.12, CZ0 + 2.4); kit.tipOn(step, "The step", "Worn smooth by the door.");
  if (P.has("vegetables")) { boxRow(); }
  function boxRow() { kit.boxTS(3, 0.2, 1.4, M(T.soil([2, 1])), M(T.planks([2, 1], "#5a3d27")), 6.4, 0.1, -7.6); const crop = art.crop("carrot", 0.7); for (let i = 0; i < 6; i++) { const s = kit.sprite(crop, 0.4, 0.5); s.position.set(5.3 + i * 0.45, 0.45, -7.6); } }
  kit.box(10, 0.12, 1.2, M(T.planks([1, 6], "#7a6448")), 9, 0.08, -2.2); kit.box(2.6, 0.12, 1.2, M(T.planks([1, 6], "#7a6448")), CX1 + 2.2, 0.08, CZ0 + 2.4);
  const note = kit.sprite(T.note(), 0.45, 0.45, false); note.position.set(CX1 + 0.62, 1.4, CZ0 + 2.1);
  kit.tipOn(note, () => ({ title: "A note on the door", text: `At my stall in ${latest.lives_here?.away_at ?? "the market"} today.` }));
  // the people: whoever lives here, and Pip if it is visiting
  const them = personAt(kit, art, who.look, () => ({ title: who.name, text: who.about || "" }));
  const pip = kit.sprite(art.pip(), 1.0, 1.375); kit.tipOn(pip, () => ({ title: "Pip", text: `${latest.pip.description || latest.pip.activity}.` }));
  const others = [];
  function update(d) {
    latest = d;
    for (const o of others) o.visible = false;
    d.present.filter((p) => p.name !== who.name).forEach((p, i) => { others[i] ??= personAt(kit, art, p.look, () => ({ title: p.name, text: p.about })); others[i].visible = true; others[i].stand(CX1 + 3 + i, 0, CZ0 + 3.2); });
  }
  update(data);
  const flats = [[-8.2, 1.0], [-13, 0.5], [-14, -4], [-9, -6], [-8.2, 1.0]];
  const along = (path, k) => { const seg = k * (path.length - 1), i = Math.min(path.length - 2, Math.floor(seg)), f = seg - i; return [path[i][0] + (path[i + 1][0] - path[i][0]) * f, path[i][1] + (path[i + 1][1] - path[i][1]) * f]; };
  kit.every((t) => {
    const min = minutesNow(latest), away = !!latest.lives_here?.away_at, asleep = min >= 23 * 60 || min < 6 * 60;
    note.visible = away; them.visible = !away && !asleep; homeLamp.strength = away || asleep ? 0 : 1;
    if (them.visible) {
      if (coastal && min < 9 * 60 && tide(min) < 0.45) { const [x, z] = along(flats, (t * 0.025) % 1); them.stand(x, x < -7 ? -0.55 : 0, z); kit.frame(them, 2 + Math.floor(t * 4) % 4); }
      else if (min >= 20 * 60) { them.stand(0.9, 0.12, -5.6); kit.frame(them, Math.floor(t * 1.2) % 2); }
      else { them.stand(-3.0, 0.12, CZ0 + 1.6); kit.frame(them, Math.floor(t * 1.2) % 2); }
    }
    const pose = poseOf(latest.pip);
    pip.visible = pose !== "away";
    if (pip.visible) { pip.position.set(them.visible ? -1.2 : CX1 + 2.4, 0.81, them.visible ? CZ0 + 2.3 : CZ0 + 3.0); kit.frame(pip, pose === "sleep" ? 6 : Math.floor(t * 1.6) % 2); }
    if (c.door) c.door.rotation.y = -Math.PI / 2 + 0.85 + (Math.sin(t * 1.3) > 0.97 ? Math.sin(t * 40) * 0.04 : 0);
  });
  return { update };
}
