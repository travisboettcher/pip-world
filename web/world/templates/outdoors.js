// Places out of doors (docs/DESIGN-world-view.md): wild places to forage, yards to dig through, and spots just to see. The land follows the
// place's setting (wood, heath, shore, marsh, hills, riverside, field, town); what can be found there lies about as small things; a yard
// has its heaps and a shed; a sight has something to look at and a bench to look from. Pip searches while it gathers.
import { goods, trees, rngFor, tide, minutesNow } from "./parts.js";
import { poseOf } from "./home.js";

export function build(kit, art, data) {
  const { THREE } = kit, T = art.T, M = (t, o) => kit.mat(t, o), season = data.now.season, kind = data.place.kind, r = rngFor(data.place.key);
  const sc = data.place.scene || {}, setting = sc.setting || (kind === "yard" ? "hills" : "wood"), P = new Set(data.place.props);
  let latest = data;
  kit.camera.position.set(0, 13, 22); kit.camera.lookAt(0, 0.2, -2);
  const ground = { heath: T.heather([15, 8]), shore: T.sand([15, 8]), marsh: T.marsh([15, 8]), town: T.cobble([15, 8]) }[setting] || T.grass([15, 8], season);
  kit.tipOn(kit.boxTS(30, 2, 16, M(ground), M(T.cliff([15, 1], season)), 0, -1, -4), () => ({ title: latest.place.label[0].toUpperCase() + latest.place.label.slice(1), text: latest.place.description || latest.place.blurb }));
  kit.boxTS(40, 1, 12, M(setting === "shore" ? T.sand([20, 6]) : T.grass([20, 6], season)), M(T.cliff([20, 1], season)), 0, -2.5, 9);
  // the setting
  if (setting === "wood") trees(kit, art, season, r, { round: Array.from({ length: 9 }, () => [-13 + r() * 26, -11 + r() * 5, 0.8 + r() * 0.6]).concat([[-11, 1.5, 1.0], [11.5, 0.5, 1.1]]), pines: Array.from({ length: 18 }, () => [-14 + r() * 28, -12.5 - r() * 3, 1.1 + r() * 0.8]) });
  else if (setting === "shore" || setting === "marsh") {
    const seaMat = M(T.sea([16, 8]), { roughness: 0.25, transparent: true, opacity: 0.9 }), sea = kit.box(40, 1, 12, seaMat, 0, -1.1, -16); sea.castShadow = false;
    kit.every((t) => { sea.position.y = -1.2 + tide(minutesNow(latest)) * 0.5; seaMat.map.offset.x = (t * 0.01) % 1; });
    for (let i = 0; i < 8; i++) { const rock = kit.box(1, 1, 1, M(T.stone([1, 1])), -12 + r() * 24, 0.2, -10 - r() * 2); rock.geometry = new THREE.DodecahedronGeometry(0.4 + r() * 0.5, 0); }
    if (setting === "marsh") { const reed = art.reed(); for (let i = 0; i < 50; i++) { const s = kit.sprite(reed, 0.5, 1.0, false); s.position.set(-13 + r() * 26, 0.45, -9 + r() * 12); } }
  } else if (setting === "hills" || setting === "heath") {
    for (let i = 0; i < 5; i++) { const hill = kit.box(1, 1, 1, M(setting === "heath" ? T.heather([3, 3]) : T.grass([3, 3], season)), -14 + i * 7 + r() * 2, -0.2, -13 - r() * 2); hill.geometry = new THREE.SphereGeometry(4 + r() * 2, 8, 6); hill.scale.y = 0.45; }
    for (let i = 0; i < 7; i++) { const rock = kit.box(1, 1, 1, M(T.stone([1, 1])), -12 + r() * 24, 0.25, -8 + r() * 10); rock.geometry = new THREE.DodecahedronGeometry(0.35 + r() * 0.4, 0); }
  } else if (setting === "riverside") {
    const water = M(T.water([14, 2]), { roughness: 0.3 }); kit.box(40, 0.3, 2.4, water, 0, 0.02, -6); kit.every((t) => { water.map.offset.x = (t * 0.03) % 1; });
    kit.box(2.2, 0.3, 3.4, M(T.planks([1, 4], "#8a6440")), 3, 0.3, -6); trees(kit, art, season, r, { round: [[-9, -10, 1.1], [8, -10.5, 1.0], [12, 1, 0.9]] });
  } else trees(kit, art, season, r, { round: [[-11, -9, 1.0], [11, -8.5, 1.1]] });
  if (P.has("lighthouse")) { const tower = kit.box(1, 1, 1, M(T.whitewash([3, 4])), -10, 3.5, -12); tower.geometry = new THREE.CylinderGeometry(0.85, 1.15, 7, 10); const lm = new THREE.MeshStandardMaterial({ color: 0x444036, emissive: 0xfff0b0, emissiveIntensity: 0 }); const lamp = kit.box(1, 1, 1, lm, -10, 7.4, -12); lamp.geometry = new THREE.CylinderGeometry(0.7, 0.7, 0.9, 10); kit.lamp(lamp, null, 1.3); kit.tipOn(tower, "The lighthouse", "It stands over the water."); }
  // the kind of place
  if (kind === "yard") {
    const rust = [0x7a5a3a, 0x8f6f4f, 0x5f6e7a, 0xb85c38, 0x6a6a62];
    for (let h = 0; h < 4; h++) { const cx = -9 + h * 5.5 + r(), cz = -6 - r() * 3; for (let i = 0; i < 14; i++) { const b = kit.box(0.3 + r() * 0.9, 0.2 + r() * 0.6, 0.3 + r() * 0.9, M(null, { color: rust[i % 5], metalness: 0.3, roughness: 0.8 }), cx + (r() - 0.5) * 3, 0.2 + r() * 0.9, cz + (r() - 0.5) * 2.4); b.rotation.set(r(), r() * 3, r()); } kit.tipOn(kit.hitbox(3.4, 1.6, 2.6, cx, 0.8, cz), "A heap of scrap", "Worth digging through, if you know what you're after."); }
    kit.box(3, 2.4, 2.4, M(T.planks([2, 2], "#5a4a3a")), 9.5, 1.2, -9.5); const sr = kit.box(3.6, 0.2, 2.8, M(T.shingles([2, 2])), 9.5, 2.6, -9.5); sr.rotation.x = 0.15;
    for (let x = -13; x <= 13; x += 1.3) kit.box(0.12, 1.0, 0.12, M(T.planks([1, 1], "#5a4a3a")), x, 0.5, -12.6);
  }
  if (kind === "sight") {
    const bench = M(T.planks([2, 1], "#7a5236")); kit.box(2.2, 0.12, 0.6, bench, 0, 0.5, 1.4); [-0.9, 0.9].forEach((dx) => kit.box(0.12, 0.5, 0.5, bench, dx, 0.25, 1.4));
    kit.tipOn(kit.hitbox(2.2, 0.8, 0.8, 0, 0.4, 1.4), "A bench", "To sit and look from.");
    if (!P.has("lighthouse")) { const stone = M(T.stone([2, 2])); [[-3, -8], [-1, -8.6], [1.2, -8.4], [3.2, -7.8]].forEach(([x, z], i) => kit.box(0.9, 2.4 + (i % 2) * 0.8, 0.7, stone, x, 1.2 + (i % 2) * 0.4, z)); kit.box(5.2, 0.6, 0.8, stone, 0.1, 3.4, -8.3); kit.tipOn(kit.hitbox(7, 4, 1.5, 0, 1.8, -8.2), "The old stones", "Something to walk out and see."); }
  }
  // what can be found here, lying about
  const finds = latest.place.finds || [];
  finds.slice(0, 10).forEach((name, i) => { const x = -9 + (i % 5) * 4.4 + r() * 1.5, z = -4 + Math.floor(i / 5) * 3.5 + r(); const g = goods(kit, name, /seed/.test(name) ? "seed" : /berr|apple|mushroom|nut/.test(name) ? "food" : "", x, 0, z, i); kit.tipOn(g, name, `To be found here, with some looking.`); });
  // Pip, searching while it gathers
  const pip = kit.sprite(art.pip(), 1.0, 1.375), spark = kit.sprite(art.spark(), 0.35, 0.35, false);
  kit.tipOn(pip, () => ({ title: "Pip", text: `${latest.pip.description || latest.pip.activity}.` }));
  const path = [[-6, -2], [4, -3.5], [7, 0.5], [-2, 1.5], [-6, -2]];
  const along = (p, k) => { const seg = k * (p.length - 1), i = Math.min(p.length - 2, Math.floor(seg)), f = seg - i; return [p[i][0] + (p[i + 1][0] - p[i][0]) * f, p[i][1] + (p[i + 1][1] - p[i][1]) * f]; };
  kit.every((t) => {
    const pose = poseOf(latest.pip); pip.visible = pose !== "away"; spark.visible = false;
    if (!pip.visible) return;
    if (pose === "gather") { const k = (t * 0.03) % 1, [x, z] = along(path, k), stop = Math.floor(t / 2.5) % 2 === 0; pip.position.set(x, 0.69, z); kit.frame(pip, stop ? Math.floor(t * 1.6) % 2 : 2 + Math.floor(t * 8) % 4); spark.visible = stop && Math.floor(t * 3) % 2 === 0; spark.position.set(x + 0.5, 0.4, z + 0.2); }
    else if (pose === "sit" && kind === "sight") { pip.position.set(0, 1.25, 1.4); kit.frame(pip, 9); }
    else { pip.position.set(-1.5, 0.69, 0.5); kit.frame(pip, Math.floor(t * 1.6) % 2); }
  });
  return { update: (d) => { latest = d; } };
}
