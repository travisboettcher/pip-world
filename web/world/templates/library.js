// The library (docs/DESIGN-world-view.md): a tall reading room opened like a dollhouse, walls of books, a reading table under a lamp,
// and Pip in a chair with a book while it reads.
import { cutaway, trees, rngFor } from "./parts.js";
import { poseOf } from "./home.js";

const LX0 = -9, LX1 = 6, LZ0 = -10, LZ1 = -3.4, LH = 4.4;

export function build(kit, art, data) {
  const { THREE } = kit, T = art.T, M = (t, o) => kit.mat(t, o), season = data.now.season, r = rngFor(data.place.key), sc = data.place.scene || {};
  let latest = data;
  kit.camera.position.set(0, 13, 21); kit.camera.lookAt(0, 0.6, -4.2);
  kit.boxTS(32, 1, 18, M(T.cobble([16, 9])), M(T.stone([16, 1])), 0, -0.5, -4);
  kit.boxTS(40, 1, 10, M(T.grass([20, 5], season)), M(T.cliff([20, 1], season)), 0, -1.6, 9);
  trees(kit, art, season, r, { round: [[10.5, -6.5, 1.0], [-12, -6, 0.9]], pines: Array.from({ length: 12 }, (_, i) => [-16 + i * 2.8 + r(), -14 - r() * 2, 1.3 + r() * 0.7]) });
  const c = cutaway(kit, art, { x0: LX0, x1: LX1, z0: LZ0, z1: LZ1, h: LH, wall: sc.walls || "stone", roof: sc.roof || "slate", door: true });
  kit.tipOn(c.floor, () => ({ title: "The library", text: latest.place.blurb || "Real books, to read for a while." }));
  // columns and steps at the front
  [LX0 + 0.6, LX0 + 3, LX1 - 3, LX1 - 0.6].forEach((x) => { const col = kit.box(1, 1, 1, M(T.whitewash([1, 3])), x, LH / 2, LZ1 + 0.9); col.geometry = new THREE.CylinderGeometry(0.28, 0.32, LH, 10); });
  kit.box(LX1 - LX0 + 1.4, 0.3, 1.6, M(T.stone([8, 1])), (LX0 + LX1) / 2, 0.15, LZ1 + 0.9);
  // walls of books, a ladder, the reading table, chairs, the lamp
  const books = M(T.books([6, 3]));
  kit.box(LX1 - LX0 - 1, LH - 0.6, 0.6, books, (LX0 + LX1) / 2, (LH - 0.6) / 2, LZ0 + 0.5);
  kit.box(0.6, LH - 0.6, 4.6, M(T.books([3, 3])), LX0 + 0.5, (LH - 0.6) / 2, LZ0 + 3.2);
  kit.tipOn(kit.hitbox(LX1 - LX0 - 1, LH - 0.6, 0.8, (LX0 + LX1) / 2, (LH - 0.6) / 2, LZ0 + 0.6), "The shelves", "Real books: Pip can browse them, or settle in and read one.");
  const ladder = kit.box(0.1, 3.4, 0.1, M(T.planks([1, 2], "#6b4a30")), 2.4, 1.7, LZ0 + 1.0); ladder.rotation.x = -0.2; const l2 = kit.box(0.1, 3.4, 0.1, M(T.planks([1, 2], "#6b4a30")), 3.0, 1.7, LZ0 + 1.0); l2.rotation.x = -0.2;
  const wood = M(T.planks([2, 1], "#7a5236"));
  const table = kit.box(3.6, 0.14, 1.4, wood, -1.4, 0.9, -6.9); [[-1.6, -0.55], [1.6, -0.55], [-1.6, 0.55], [1.6, 0.55]].forEach(([dx, dz]) => kit.box(0.14, 0.85, 0.14, wood, -1.4 + dx, 0.42, -6.9 + dz));
  const openBook = new THREE.Mesh(new THREE.PlaneGeometry(0.7, 0.45), M(T.book())); openBook.rotation.x = -Math.PI / 2; openBook.position.set(-0.6, 0.98, -6.6); kit.scene.add(openBook);
  kit.tipOn(table, () => ({ title: "The reading table", text: latest.pip.session?.kind === "read" && latest.pip.here ? `Pip is reading ${latest.pip.session.target}.` : "A long table under a green-shaded lamp." }));
  [[-2.6, -5.6], [0.4, -5.6]].forEach(([x, z]) => { kit.box(0.8, 0.5, 0.8, M(null, { color: 0x6a2f2a }), x, 0.25, z); kit.box(0.8, 0.8, 0.2, M(null, { color: 0x6a2f2a }), x, 0.75, z + 0.35); });
  const lampMat = new THREE.MeshStandardMaterial({ color: 0x2a4a2a, emissive: 0xffd080, emissiveIntensity: 0 }); const lampLight = new THREE.PointLight(0xffc070, 0, 8, 2); lampLight.position.set(-1.4, 2.2, -6.6); kit.scene.add(lampLight);
  kit.box(0.06, 0.5, 0.06, M(null, { color: 0x3a3a2a }), -1.4, 1.2, -7.2); kit.lamp(kit.box(0.6, 0.25, 0.4, lampMat, -1.4, 1.5, -7.2), lampLight, 0.9);
  const win = M(T.window(false), { emissive: 0xffb050, emissiveMap: T.window(true), emissiveIntensity: 0 }); kit.lamp(kit.plane(1.0, 1.4, win, LX1 - 1.4, 3.3, LZ0 + 0.21), null, 0.6);
  // Pip: reading at the table, or browsing the shelves
  const pip = kit.sprite(art.pip(), 1.0, 1.375); kit.tipOn(pip, () => ({ title: "Pip", text: `${latest.pip.description || latest.pip.activity}.` }));
  const book = kit.sprite(art.bubble("#8a3a2a"), 0.5, 0.42, false);
  kit.every((t) => {
    const pose = poseOf(latest.pip); pip.visible = pose !== "away"; book.visible = pose === "read";
    if (pose === "read") { pip.position.set(-2.6, 1.2, -5.5); kit.frame(pip, 9); book.position.set(-2.1, 2.1 + Math.sin(t * 2) * 0.03, -5.4); }
    else if (pip.visible) { const k = (Math.sin(t * 0.25) + 1) / 2; pip.position.set(-5 + k * 6, 0.81, LZ0 + 1.6); kit.frame(pip, Math.abs(Math.cos(t * 0.25)) > 0.2 ? 2 + Math.floor(t * 8) % 4 : Math.floor(t * 1.6) % 2); pip.scale.x = Math.cos(t * 0.25) >= 0 ? 1 : -1; }
  });
  return { update: (d) => { latest = d; } };
}
