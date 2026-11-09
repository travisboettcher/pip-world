// A shop (docs/DESIGN-world-view.md): a shopfront opened like a dollhouse, a counter with the keeper behind it, its stock on shelves or in
// a wall of drawers, and what its record mentions (rope, lanterns, boats at a harbour). Shut: the keeper gone home, a note on the door.
import { goods, cutaway, personAt, rngFor } from "./parts.js";
import { poseOf } from "./home.js";

const SX0 = -8, SX1 = 4, SZ0 = -9.5, SZ1 = -3.6;

export function build(kit, art, data) {
  const { THREE } = kit, T = art.T, M = (t, o) => kit.mat(t, o), season = data.now.season, P = new Set(data.place.props), r = rngFor(data.place.key);
  let latest = data;
  kit.camera.position.set(0, 13, 22); kit.camera.lookAt(0, 0.4, -3);
  const harbour = P.has("boats") && data.place.coastal;
  kit.tipOn(kit.boxTS(32, 1, 16, M(T.cobble([16, 8])), M(T.stone([16, 1])), 0, -0.5, -4), () => ({ title: latest.place.label, text: latest.place.description || latest.place.blurb }));
  if (harbour) {
    const seaMat = M(T.sea([16, 4]), { roughness: 0.25, transparent: true, opacity: 0.9 }); kit.box(40, 0.6, 8, seaMat, 0, -1.2, 8);
    kit.boxTS(40, 1.2, 0.6, M(T.stone([20, 1])), M(T.stone([20, 1])), 0, -0.6, 4.1);
    for (let i = 0; i < 2; i++) { const hull = kit.box(3.2, 0.7, 1.2, M(T.planks([3, 1], ["#6b4a30", "#3f5a6a"][i])), -6 + i * 9, -0.75, 6.5 + i * 1.2); hull.rotation.y = 0.1 - i * 0.2; kit.box(0.1, 2.4, 0.1, M(T.planks([1, 2], "#5a3d27")), -6 + i * 9, 0.6, 6.5 + i * 1.2); kit.tipOn(hull, "A boat", "Tied up at the harbour wall."); }
    kit.every((t) => { seaMat.map.offset.x = (t * 0.01) % 1; });
  } else kit.boxTS(40, 1, 10, M(T.grass([20, 5], season)), M(T.cliff([20, 1], season)), 0, -1.6, 9);
  const roof = ["shingle", "slate", "thatch"][Math.floor(r() * 3)];
  const c = cutaway(kit, art, { x0: SX0, x1: SX1, z0: SZ0, z1: SZ1, h: 3.4, wall: harbour ? "stone" : "planks", roof });
  // the counter, the stock behind it, the keeper
  const counter = kit.box(8.5, 1.0, 0.9, M(T.planks([4, 1], "#7a5236")), -2.2, 0.5, -5.3);
  const booth = data.booths[0] || { items: [] };
  const back = P.has("drawers") ? M(T.drawers([6, 2])) : M(T.planks([3, 2], "#6b4a30"));
  kit.box(10, 2.4, 0.5, back, -2.2, 1.3, SZ0 + 0.5);
  [0.9, 1.7, 2.5].forEach((y) => kit.box(10, 0.08, 0.6, M(T.planks([4, 1], "#5a3d27")), -2.2, y, SZ0 + 0.85));
  booth.items.slice(0, 9).forEach((it, i) => goods(kit, it.name, it.kind, -6.4 + (i % 9) * 1.05, 0.95 + (i % 3) * 0.8, SZ0 + 0.95, i));
  booth.items.slice(0, 4).forEach((it, i) => goods(kit, it.name, it.kind, -5.2 + i * 1.6, 1.0, -5.3, i));
  const priced = () => (latest.booths[0]?.items || []).map((i) => `${i.name} (${i.price} coin${i.price === 1 ? "" : "s"}${i.left ? "" : ", sold out"})`).join(", ");
  kit.tipOn(counter, () => ({ title: "The counter", text: priced() ? `In stock: ${priced()}.` : "Bare shelves today." }));
  if (P.has("rope")) for (let i = 0; i < 3; i++) { const coil = kit.box(1, 1, 1, M(null, { color: 0x9a8a5a }), -7.2 + i * 0.7, 2.6, SZ0 + 1.0); coil.geometry = new THREE.TorusGeometry(0.28, 0.09, 6, 12); kit.tipOn(coil, "Coils of rope", "Hung on pegs along the wall."); }
  if (P.has("lanterns")) for (let i = 0; i < 3; i++) { kit.box(0.04, 0.8, 0.04, M(T.planks([1, 1], "#3f3326")), -5 + i * 2.6, 2.9, -6.6); const lm = new THREE.MeshStandardMaterial({ color: 0x332211, emissive: 0xffc070, emissiveIntensity: 0 }); kit.lamp(kit.box(0.34, 0.4, 0.34, lm, -5 + i * 2.6, 2.4, -6.6), null, 0.9); }
  const shopLight = new THREE.PointLight(0xffb066, 0, 10, 2); shopLight.position.set(-2, 2.6, -6.5); kit.scene.add(shopLight); kit.lamps.push({ mesh: counter, light: shopLight, strength: 0 });
  const look = { height: ["short", "medium", "tall"][Math.floor(r() * 3)], hair: ["grey", "black", "brown", "white"][Math.floor(r() * 4)], skin: ["pale", "light", "olive", "brown", "dark"][Math.floor(r() * 5)], top: ["brown", "green", "blue"][Math.floor(r() * 3)], bottom: "brown", accessory: "apron" };
  const keeper = personAt(kit, art, data.present[0]?.look || look, () => ({ title: data.present[0]?.name || "The keeper", text: `Keeps ${latest.place.label}.` }));
  keeper.stand(-3.0, 0.12, -6.4);
  const note = kit.sprite(T.note(), 0.45, 0.45, false); note.position.set(SX1 + 0.62, 1.4, SZ0 + 2.1); kit.tipOn(note, () => ({ title: "Shut", text: latest.place.hours ? `Open ${latest.place.hours[0]}:00 to ${latest.place.hours[1]}:00.` : "Shut for now." }));
  const pip = kit.sprite(art.pip(), 1.0, 1.375); kit.tipOn(pip, () => ({ title: "Pip", text: `${latest.pip.description || latest.pip.activity}.` }));
  kit.every((t) => {
    const open = latest.place.open; keeper.visible = open; note.visible = !open; kit.frame(keeper, Math.floor(t * 1.1) % 2);
    const pose = poseOf(latest.pip); pip.visible = pose !== "away";
    if (pip.visible) { pip.position.set(-1.2, 0.81, -4.3); kit.frame(pip, Math.floor(t * 1.6) % 2); }
  });
  return { update: (d) => { latest = d; } };
}
