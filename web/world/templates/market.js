// A market square (docs/DESIGN-world-view.md): booths built from what the engine says each sells, a stall for any character keeping one
// here today, Pip's own stall with what it set out, houses round the square, and people. Shut: awnings rolled, the square empty.
import { goods, trees, personAt, rngFor } from "./parts.js";
import { poseOf } from "./home.js";

const SLOTS = [[-9.5, -8.2], [-4.4, -9.0], [4.6, -9.0], [9.8, -7.6], [9.6, -3.4], [-10.6, -3.6]], PIP_SLOT = [-5.4, -1.6];
const AWNINGS = [["#b5402f", "#efe2c0"], ["#4f7d4a", "#efe2c0"], ["#c98a2a", "#efe2c0"], ["#4a6a8a", "#dfe6ea"], ["#6a4a7a", "#efe2c0"], ["#7a6448", "#efe2c0"]];
const SKINS = ["pale", "light", "olive", "brown", "dark"], HAIRS = ["white", "grey", "black", "brown", "auburn", "fair"], CLOTH = ["grey", "brown", "green", "blue", "red", "ochre", "plum", "cream"];

export function build(kit, art, data) {
  const { THREE } = kit, T = art.T, M = (t, o) => kit.mat(t, o), season = data.now.season, P = new Set(data.place.props), r = rngFor(data.place.key);
  let latest = data;
  const pick = (a) => a[Math.floor(r() * a.length)], someone = (apron) => ({ height: pick(["short", "medium", "medium", "tall"]), hair: pick(HAIRS), skin: pick(SKINS), top: pick(CLOTH), bottom: pick(["grey", "brown", "navy", "black"]), accessory: apron ? "apron" : pick(["hat", "scarf", "satchel", "none", "none"]) });
  kit.camera.position.set(0, 13, 22); kit.camera.lookAt(0, 0.4, -3);
  kit.tipOn(kit.boxTS(32, 1, 20, M(T.cobble([16, 10])), M(T.stone([16, 1])), 0, -0.5, -4), () => ({ title: latest.place.label, text: latest.place.description || latest.place.blurb }));
  kit.boxTS(40, 1, 10, M(T.grass([20, 5], season)), M(T.cliff([20, 1], season)), 0, -1.6, 11);
  kit.boxTS(46, 5, 8, M(T.grass([23, 4], season)), M(T.cliff([23, 2], season)), 0, 1.0, -22);
  trees(kit, art, season, r, { pines: Array.from({ length: 16 }, (_, i) => [-22 + i * 2.9 + r(), -21 - r() * 2, 1.2 + r() * 0.8, 3.5]) });
  // houses round the square, lit at night
  const shingle = T.shingles([3, 2]);
  let hx = -14.2;
  while (hx < 13) {
    const w = 3.4 + r() * 1.6, h = 3.6 + r() * 1.4, x = hx + w / 2; hx += w + 0.2;
    kit.box(w, h, 3, M(T.plaster([Math.round(w / 2), 1])), x, h / 2, -13.5);
    const roofT = r() > 0.4 ? ({ thatch: T.thatch([3, 2]), slate: T.slate([3, 2]), tile: T.tiles([3, 2]) }[data.place.scene?.roof] || shingle) : (r() > 0.5 ? T.thatch([3, 2]) : shingle);
    [0.7, -0.7].forEach((tilt, k) => { const rf = kit.box(w + 0.6, 0.3, 2.4, M(roofT), x, h + 0.6, k ? -14.4 : -12.6); rf.rotation.x = tilt; });
    const wm = M(T.window(false), { emissive: 0xffb050, emissiveMap: T.window(true), emissiveIntensity: 0 });
    [-w / 4, w / 4].forEach((dx) => kit.lamp(kit.plane(0.8, 0.8, wm, x + dx, h * 0.68, -11.99), null, r() > 0.3 ? 0.9 : 0.3));
    kit.plane(0.9, 1.4, M(T.door()), x, 0.7, -11.99);
  }
  if (P.has("well") || r() > 0.4) { const well = kit.box(1, 1, 1, M(T.stone([3, 1])), 0, 0.45, -5.2); well.geometry = new THREE.CylinderGeometry(0.9, 0.95, 0.9, 12); [-0.75, 0.75].forEach((dx) => kit.box(0.14, 1.8, 0.14, M(T.planks([1, 2], "#6b4a30")), dx, 1.3, -5.2)); kit.box(2.0, 0.12, 1.4, M(T.thatch([2, 1])), 0, 2.3, -5.2); kit.tipOn(well, "The well", "Where people stop to talk."); }
  if (P.has("barrow")) { const wood = M(T.planks([2, 1], "#7a5236")); kit.tipOn(kit.box(1.8, 0.5, 1.0, wood, 6.2, 0.75, -2.0), "A barrow", "Wheeled in at dawn."); [-0.7, 0.7].forEach((dx) => { const w = kit.box(1, 1, 1, wood, 6.2 + dx, 0.35, -1.4); w.geometry = new THREE.CylinderGeometry(0.35, 0.35, 0.1, 10); w.rotation.x = Math.PI / 2; }); for (let i = 0; i < 9; i++) { const v = kit.box(1, 1, 1, M(null, { color: [0x6fa047, 0xd8b24a, 0x8a4a6a][i % 3] }), 5.6 + (i % 3) * 0.45, 1.1, -2.3 + Math.floor(i / 3) * 0.3); v.geometry = new THREE.SphereGeometry(0.16, 6, 5); } }
  if (P.has("crates")) [[-12.5, -4], [-11.6, -4.2], [-12.1, -3.2]].forEach(([x, z], i) => kit.box(0.8, 0.7, 0.8, M(T.planks([1, 1], "#9a7048")), x + 1, 0.35 + (i === 2 ? 0.7 : 0), z + 4));
  if (P.has("bunting") || true) { const cols = ["#b5402f", "#e8b04a", "#4f7d4a", "#4a6a8a", "#efe2c0"], bunt = []; for (let i = 0; i < 28; i++) { const k = (i % 14) / 13, x0 = i < 14 ? -13 : 0, x = x0 + 13 * k, y = 4.4 - Math.sin(k * Math.PI) * 0.9; const tri = new THREE.Mesh(new THREE.ConeGeometry(0.2, 0.4, 3), M(null, { color: cols[i % 5] })); tri.rotation.x = Math.PI; tri.position.set(x, y, -11.3); kit.scene.add(tri); bunt.push(tri); } kit.every((t) => bunt.forEach((b, i) => { b.rotation.z = Math.sin(t * 2 + i) * 0.15; })); }
  [[-2.8, -3.0], [3.0, -3.0]].forEach(([x, z]) => { kit.box(0.14, 2.6, 0.14, M(T.planks([1, 2], "#3f3326")), x, 1.3, z); const lm = new THREE.MeshStandardMaterial({ color: 0x222222, emissive: 0xffc070, emissiveIntensity: 0 }); const l = new THREE.PointLight(0xffb066, 0, 8, 2); l.position.set(x, 2.6, z + 0.3); kit.scene.add(l); kit.lamp(kit.box(0.32, 0.4, 0.32, lm, x, 2.75, z), l); });

  // a stall: trestle, posts, an awning (rolled when shut), goods, and someone behind it
  function stall(x, z, colours) {
    const wood = M(T.planks([2, 1], "#8a6440")), post = M(T.planks([1, 2], "#5a3d27")), s = { goods: [], x, z };
    s.table = kit.box(3.0, 0.14, 1.1, wood, x, 0.9, z);
    [[-1.35, -0.45], [1.35, -0.45], [-1.35, 0.45], [1.35, 0.45]].forEach(([dx, dz]) => kit.box(0.12, 0.84, 0.12, post, x + dx, 0.42, z + dz));
    kit.box(0.14, 2.6, 0.14, post, x - 1.45, 1.3, z - 0.75); kit.box(0.14, 2.6, 0.14, post, x + 1.45, 1.3, z - 0.75); kit.box(0.14, 2.0, 0.14, post, x - 1.45, 1.0, z + 0.75); kit.box(0.14, 2.0, 0.14, post, x + 1.45, 1.0, z + 0.75);
    const stripes = M(T.stripes(...colours)); s.awning = kit.box(3.3, 0.08, 1.9, stripes, x, 2.35, z); s.awning.rotation.x = 0.32;
    s.rolled = kit.box(1, 1, 1, stripes, x, 2.55, z - 0.75); s.rolled.geometry = new THREE.CylinderGeometry(0.16, 0.16, 3.2, 8); s.rolled.rotation.z = Math.PI / 2;
    s.show = (items) => {
      s.goods.forEach((g) => kit.scene.remove(g)); s.goods = [];
      items.slice(0, 4).forEach((it, i) => {
        const gx = x - 1.15 + i * (2.3 / Math.max(1, Math.min(4, items.length) - 1 || 1));
        if (["work", "creation"].includes(it.kind)) return;                // Pip's own made things: a module shows them (stall-pictures)
        for (let k = 0; k < 3; k++) s.goods.push(goods(kit, it.name || it.item, it.kind || "", gx + (k - 1) * 0.16, 0.97, z - 0.2 + (k % 2) * 0.3, k));
      });
    };
    return s;
  }
  const stalls = [], keepers = [];
  const own = data.booths.filter((b) => !b.whose).flatMap((b) => { const groups = []; for (let i = 0; i < b.items.length && groups.length < 3; i += 3) groups.push({ booth: b.booth, whose: "", items: b.items.slice(i, i + 3) }); return groups; });
  const theirs = data.booths.filter((b) => b.whose);
  const priced = (items) => items.map((i) => `${i.name} (${i.price} coin${i.price === 1 ? "" : "s"}${i.left ? "" : ", sold out"})`).join(", ");
  [...own, ...theirs].slice(0, SLOTS.length).forEach((b, i) => {
    const [x, z] = SLOTS[i], s = stall(x, z, AWNINGS[i % AWNINGS.length]); s.show(b.items); stalls.push(s);
    const look = b.whose ? b.look : someone(true), k = personAt(kit, art, look, () => { const now = latest.booths.find((q) => q.booth === b.booth && q.whose === b.whose) || b; return { title: b.whose || "A stallholder", text: `Selling ${priced(now.whose ? now.items : b.items)}.` }; });
    k.stand(x + 0.4, 0, z - 1.0); keepers.push(k);
    kit.tipOn(s.table, () => ({ title: b.whose ? `${b.whose}'s stall` : "A stall", text: `${priced(b.items)}. Prices move a little every day.` }));
  });
  const pipStall = stall(PIP_SLOT[0], PIP_SLOT[1], ["#d8c8a4", "#cdbb94"]);
  kit.tipOn(pipStall.table, () => ({ title: latest.stall.length ? "Pip's stall" : "A free stall", text: latest.stall.length ? `${latest.stall.map((s) => `${s.qty} ${s.item} at ${s.ask} coins`).join(", ")}.` : "Anyone can set out goods here." }));
  // people about the square
  const route = [[-8, -4.5], [-3, -6], [2, -6.2], [7, -5], [9.5, -4.8], [8, -2.2], [2, -1.2], [-3, -2.6], [-8, -4.5]];
  const along = (path, k) => { const seg = k * (path.length - 1), i = Math.min(path.length - 2, Math.floor(seg)), f = seg - i; return [path[i][0] + (path[i + 1][0] - path[i][0]) * f, path[i][1] + (path[i + 1][1] - path[i][1]) * f]; };
  const shoppers = Array.from({ length: 8 }, (_, i) => { const p = personAt(kit, art, someone(false), () => ({ title: "Someone shopping", text: "Here for the market." })); p.userData.k = i / 8; p.userData.speed = 0.012 + r() * 0.01; p.userData.lane = (r() - 0.5) * 1.2; return p; });
  const pip = kit.sprite(art.pip(), 1.0, 1.375); kit.tipOn(pip, () => ({ title: "Pip", text: `${latest.pip.description || latest.pip.activity}.` }));
  function update(d) { latest = d; pipStall.show(d.stall); }
  update(data);
  kit.every((t) => {
    const open = latest.place.open;
    [...stalls, pipStall].forEach((s, i) => { const up = open && (s !== pipStall || latest.stall.length > 0); s.awning.visible = up; s.rolled.visible = !up; s.goods.forEach((g) => { g.visible = up; }); });
    keepers.forEach((k, i) => { k.visible = open; kit.frame(k, Math.floor(t * 1.1 + i) % 2); });
    shoppers.forEach((s, i) => { s.visible = open; if (!open) return; const k = (s.userData.k + t * s.userData.speed) % 1, [x, z] = along(route, k), [px] = along(route, (k + 0.995) % 1); s.stand(x + s.userData.lane, 0, z + s.userData.lane * 0.6); s.scale.x = x < px ? -1 : 1; kit.frame(s, 2 + Math.floor(t * 6 + i) % 4); });
    const pose = poseOf(latest.pip); pip.visible = pose !== "away";
    if (pip.visible) { if (latest.stall.length) pip.position.set(PIP_SLOT[0] + 0.4, 0.69, PIP_SLOT[1] - 1.1); else pip.position.set(-1.5, 0.69, -1.0); kit.frame(pip, Math.floor(t * 1.6) % 2); }
  });
  return { update };
}
