// The home scene (docs/DESIGN-world-view.md): Pip's workshop opened like a dollhouse, its garden, the terrace, the stream and the bridge.
// Built once; `update` moves it to the latest /world/scene data (plots, creations, belongings, Pip) without rebuilding.
import { hashStr } from "../art.js";

const WX0 = -10.5, WX1 = -1.5, WZ0 = -7, WZ1 = -1.6, WH = 3.4, WMID = (WX0 + WX1) / 2, RZ = (WZ0 + WZ1) / 2;
const WALKS = /\b(walk|walks|walker|legs?|crawl|hop|creature|toddle|scuttle)\b/i;
const STOOL = [-3.6, WZ0 + 2.35], BENCH = [-6.6, WZ0 + 2.25];
const hours = (min) => (min < 60 ? `${min} minutes` : `${Math.round(min / 60)} hours`);

export function poseOf(pip) {           // what Pip is doing, as a pose: the one place facts become animation
  if (!pip.here) return "away";
  if (pip.asleep) return "sleep";
  const s = pip.session, a = `${pip.activity} ${pip.description}`.toLowerCase();
  if (s && (s.kind === "work" || s.kind === "experiment")) return "work";
  if (/garden|plot|plant|harvest|water|weed|tend/.test(a) && !/wait|rest/.test(a)) return "garden";
  if (/wait|rest|sit|read|think|eat|bench/.test(a)) return "sit";
  return "idle";
}

export function build(kit, art, data) {
  const { THREE } = kit, T = art.T, season = data.now.season, M = (t, o) => kit.mat(t, o);
  kit.camera.position.set(0, 13, 22); kit.camera.lookAt(0, 0.2, -1.5);
  // ground: terrace, cliff, stream, meadow, a hill behind
  kit.boxTS(30, 2, 16, M(T.grass([15, 8], season)), M(T.cliff([15, 1], season)), 0, -1, -4);
  kit.boxTS(40, 1, 12, M(T.grass([20, 6], season)), M(T.cliff([20, 1], season)), 0, -2.5, 9);
  const water = M(T.water([14, 2]), { roughness: 0.3 }); kit.box(40, 0.3, 2.6, water, 0, -2.0, 5.6);
  kit.boxTS(30, 0.6, 0.4, M(T.stone([15, 1])), M(T.stone([15, 1])), 0, -1.9, 4.2);
  kit.boxTS(40, 4, 6, M(T.grass([20, 3], season)), M(T.cliff([20, 2], season)), 0, 1.2, -14);
  kit.tipOn(kit.box(2.2, 0.25, 3.4, M(T.planks([1, 4], "#8a6440")), 6, -1.55, 5.6), "The bridge", "Over the stream, and on to everywhere else.");
  // the workshop, opened like a dollhouse
  kit.tipOn(kit.boxTS(WX1 - WX0, 0.12, WZ1 - WZ0, M(T.floor([5, 3])), M(T.planks([5, 1], "#5a3d27")), WMID, 0.06, RZ), "The workshop", "Pip's home: a bench, a stool, a shelf, and whatever is being made.");
  const inner = M(T.inner([6, 2])), outer = M(T.plaster([2, 1]));
  kit.box(WX1 - WX0, WH, 0.3, [outer, outer, outer, outer, inner, outer], WMID, WH / 2, WZ0);
  kit.box(0.3, WH, WZ1 - WZ0, [outer, inner, outer, outer, outer, outer], WX0, WH / 2, RZ);
  kit.box(0.3, WH, 1.6, [outer, inner, outer, outer, outer, outer], WX1, WH / 2, WZ0 + 0.8);
  kit.box(0.3, WH, 1.9, [outer, inner, outer, outer, outer, outer], WX1, WH / 2, WZ1 - 0.95);
  kit.box(0.3, 1.0, 1.9, outer, WX1, WH - 0.5, RZ - 0.15);
  const door = new THREE.Mesh(new THREE.PlaneGeometry(1.4, 2.2), M(T.door())); door.position.set(WX1 + 0.6, 1.15, RZ - 0.15); door.rotation.y = -Math.PI / 2 + 0.9; kit.scene.add(door);
  const timber = M(T.planks([1, 2], "#4a2f1f"));
  [WX0, WX1].forEach((x) => kit.box(0.36, WH, 0.36, timber, x, WH / 2, WZ1)); kit.box(WX1 - WX0 + 0.36, 0.3, 0.36, timber, WMID, 0.15, WZ1); kit.box(WX1 - WX0 + 0.36, 0.36, 0.36, timber, WMID, WH, WZ1);
  const roof = kit.box(WX1 - WX0 + 1.2, 0.35, 3.8, M(T.thatch([5, 2])), WMID, WH + 1.1, WZ0 + 1.2); roof.rotation.x = -0.62;
  const gable = new THREE.Shape(); gable.moveTo(WZ0, 0); gable.lineTo(WZ1, 0); gable.lineTo(RZ, 2.2); gable.closePath();
  [WX0 - 0.15, WX1 + 0.15].forEach((x) => { const g = new THREE.Mesh(new THREE.ShapeGeometry(gable), M(T.planks([2, 1], "#6b4529"), { side: THREE.DoubleSide })); g.rotation.y = -Math.PI / 2; g.position.set(x, WH, 0); g.castShadow = true; kit.scene.add(g); });
  kit.box(0.7, 2.4, 0.7, M(T.stone([1, 2])), WX0 + 1.4, WH + 1.6, WZ0 + 0.6);
  const win = M(T.window(false), { emissive: 0xffb050, emissiveMap: T.window(true), emissiveIntensity: 0 });
  kit.lamp(kit.tipOn(kit.plane(1.3, 1.3, win, -3.9, 2.0, WZ0 + 0.16), "The window", "Looks out back, over the hill and the pines."), null, 0.9);
  // inside: the shelf, the bench and its tools, the stool, the lamp
  kit.box(3.2, 0.12, 0.5, timber, -8.4, 2.25, WZ0 + 0.4);
  [["#7fb3a8", 0.24, 0.42], ["#c9a24a", 0.3, 0.34], ["#9b6b9e", 0.24, 0.5], ["#7fb3a8", 0.32, 0.3], ["#b85c38", 0.24, 0.4], ["#cfcfcf", 0.3, 0.45]].forEach(([c, w, h], i) => kit.box(w, h, w, M(null, { color: c, roughness: 0.4 }), -9.6 + i * 0.5, 2.31 + h / 2, WZ0 + 0.4));
  const shelfTip = kit.box(3.2, 1.0, 0.6, M(null, { transparent: true, opacity: 0 }), -8.4, 2.6, WZ0 + 0.4); shelfTip.castShadow = false;
  let latest = data;
  kit.tipOn(shelfTip, () => ({ title: "Belongings", text: (latest.items || []).map((i) => `${i.name} ×${i.qty}`).join(", ") + `; ${latest.coins ?? 0} coins.` }));
  const bench = M(T.planks([3, 1], "#7a5236"));
  kit.tipOn(kit.box(3.6, 0.2, 1.2, bench, -6.4, 1.1, WZ0 + 1.3), () => ({ title: "The bench", text: latest.pip.session?.project ? `Pip is working on ${latest.pip.session.project}${latest.pip.session.stage ? ` (${latest.pip.session.stage})` : ""}.` : "Where Pip works on its projects." }));
  [[-7.9, -0.4], [-4.9, -0.4], [-7.9, 0.4], [-4.9, 0.4]].forEach(([x, dz]) => kit.box(0.18, 1.0, 0.18, bench, x, 0.5, WZ0 + 1.3 + dz));
  kit.box(0.6, 0.06, 0.12, M(null, { color: 0xb8b8b8, metalness: 0.7, roughness: 0.3 }), -7.2, 1.23, WZ0 + 1.2);
  kit.box(0.7, 0.12, 0.7, bench, STOOL[0], 0.75, WZ0 + 2.3); [-0.25, 0.25].forEach((dx) => kit.box(0.1, 0.7, 0.1, bench, STOOL[0] + dx, 0.35, WZ0 + 2.3));
  kit.box(0.04, 1.0, 0.04, timber, -6.2, WH - 0.5, WZ0 + 2.2);
  const lampMat = new THREE.MeshStandardMaterial({ color: 0x332211, emissive: 0xffc070, emissiveIntensity: 0 }); const lampLight = new THREE.PointLight(0xffb066, 0, 9, 2); lampLight.position.set(-6.2, WH - 1.4, WZ0 + 2.4); kit.scene.add(lampLight);
  kit.lamp(kit.box(0.4, 0.3, 0.4, lampMat, -6.2, WH - 1.1, WZ0 + 2.2), lampLight, 1.1);
  // fence, lantern, paths, steps
  const fence = M(T.planks([1, 1], "#8a6440"));
  for (let x = 0; x <= 8.5; x += 0.85) kit.box(0.14, 0.8, 0.14, fence, x, 0.4, -7.2);
  kit.box(8.6, 0.1, 0.08, fence, 4.25, 0.6, -7.2); kit.box(8.6, 0.1, 0.08, fence, 4.25, 0.3, -7.2);
  const lanternMat = new THREE.MeshStandardMaterial({ color: 0x222222, emissive: 0xffc070, emissiveIntensity: 0 }); const lanternLight = new THREE.PointLight(0xffb066, 0, 7, 2); lanternLight.position.set(-0.7, 1.8, -0.9); kit.scene.add(lanternLight);
  kit.box(0.12, 1.8, 0.12, timber, -0.95, 0.9, -1.2); kit.lamp(kit.box(0.3, 0.36, 0.3, lanternMat, -0.95, 1.9, -1.2), lanternLight);
  kit.boxTS(1.6, 0.06, 1.6, M(T.cobble([1, 1])), M(T.cobble([1, 1])), -0.6, 0.03, RZ);
  kit.boxTS(1.6, 0.06, 7, M(T.cobble([1, 4])), M(T.cobble([1, 4])), 0.2, 0.03, -0.1);
  kit.boxTS(6.2, 0.06, 1.6, M(T.cobble([4, 1])), M(T.cobble([4, 1])), 3.3, 0.04, 2.6);
  for (let i = 0; i < 4; i++) kit.boxTS(1.6, 0.5, 0.55, M(T.stone([1, 1])), M(T.stone([1, 1])), 6, -0.25 - i * 0.45, 3.6 + i * 0.5);
  // trees in the season's colours, pines on the hill, flowers along the edge
  const leaf = M(T.leaves([2, 2], season)), pine = M(T.leaves([2, 2], season, season === "winter" ? "#3f5a46" : "#2f6a3a")), trunk = M(T.planks([1, 2], "#5a3d27")), sway = [];
  const r = (() => { let s = 77; return () => (s = (s * 16807) % 2147483647) / 2147483647; })();
  kit.box(0.6, 1.8, 0.6, trunk, 11.2, 0.9, -4.5);
  [[0, 2.4, 0, 1.5], [0.8, 2.0, 0.3, 1.0], [-0.8, 2.1, -0.2, 1.1], [0.2, 3.1, -0.3, 1.0]].forEach(([dx, dy, dz, rad]) => { const m = kit.box(1, 1, 1, leaf, 11.2 + dx * 1.15, dy * 1.15, -4.5 + dz * 1.15); m.geometry = new THREE.IcosahedronGeometry(rad * 1.15, 0); m.userData.sway = r() * 6; sway.push(m); });
  for (let i = 0; i < 14; i++) { const x = -15 + i * 2.3 + r(), z = -12.5 - r() * 2, s = 1.2 + r() * 0.8; kit.box(0.3 * s, s, 0.3 * s, trunk, x, 3.2 + 0.5 * s, z); [[1.4, 1.6], [1.1, 2.5], [0.75, 3.3]].forEach(([rad, h]) => { const m = kit.box(1, 1, 1, pine, x, 3.2 + h * s, z); m.geometry = new THREE.ConeGeometry(rad * s, 1.4 * s, 7); }); }
  const flowerTex = art.flower();
  for (let i = 0; i < 40; i++) { const f = Math.floor(r() * 4), t = flowerTex.clone(); t.needsUpdate = true; t.offset.set(f / 4, 0); const s = kit.sprite(t, 0.42, 0.42, false); const front = i < 26;
    s.position.set(-13 + r() * 26, front ? 0.2 : -1.8, front ? 2.4 + r() * 1.4 : 7.4 + r() * 2.5); if ((front && s.position.x > 5 && s.position.x < 7) || (season === "winter" && f < 3)) s.visible = false; }

  // the live parts: plots, creations, Pip
  const plots = [];
  function plotsFor(garden) {
    const shown = garden.slice(0, 4);
    while (plots.length < shown.length) {
      const i = plots.length, x = 1.4 + i * 2.4, z = -5.2;
      const soil = kit.tipOn(kit.boxTS(1.9, 0.25, 2.8, M(T.soil([1, 2])), M(T.planks([1, 1], "#5a3d27")), x, 0.12, z), () => {
        const g = latest.garden[i]; if (!g || g.state === "empty") return { title: `Plot ${i + 1}`, text: "Empty, ready to plant." };
        return { title: `Plot ${g.plot}: ${g.crop}`, text: g.state === "ready" ? "Ripe now, ready to harvest." : `${Math.round(progress(g) * 100)}% grown; ripe in about ${hours(g.ready_in_min)}.` };
      });
      const sprites = []; for (let k = 0; k < 4; k++) { const s = kit.sprite(art.crop("x", 0), 0.9, 1.12); s.position.set(x - 0.4 + (k % 2) * 0.8, 0.78, z - 0.7 + Math.floor(k / 2) * 1.3); sprites.push(s); }
      plots.push({ soil, sprites, key: "" });
    }
    shown.forEach((g, i) => {
      const p = plots[i], key = g.state === "empty" ? "empty" : `${g.crop}|${g.state}|${Math.round(progress(g) * 10)}`;
      if (key === p.key) return; p.key = key;
      if (g.state === "empty") { p.sprites.forEach((s) => { s.visible = false; }); return; }
      const t = art.crop(g.crop, progress(g), g.state === "ready");
      p.sprites.forEach((s) => { s.visible = true; s.material.map = t; s.material.needsUpdate = true; s.customDepthMaterial.map = t; });
    });
  }
  const progress = (g) => (g.ready_at > g.planted_at ? Math.max(0, Math.min(1, 1 - (g.ready_at - Date.now() / 1000) / (g.ready_at - g.planted_at))) : 1);

  const made = new Map();                                          // name -> {mesh, kind, clock?}
  function creationsFor(list) {
    let wall = 0, floor = 0, shelf = 0;
    for (const c of list) {
      if (made.has(c.name)) continue;
      let e;
      if (c.clock) { const ck = art.clock(); const m = kit.sprite(ck.texture, 0.85, 1.5, false); m.quaternion.identity(); m.position.set(-2.4 - wall * 1.2, 1.9, WZ0 + 0.22); wall++; e = { mesh: m, kind: "clock", ck }; }
      else if (WALKS.test(c.description) || c.capabilities.includes("companion")) { const t = art.walker(); const m = kit.sprite(t, 0.8, 0.57); e = { mesh: m, kind: "walker", t, lane: floor++ }; }
      else { const m = kit.sprite(art.contraption(c.quality, hashStr(c.name)), 0.5, 0.5, false); m.position.set(-9.4 + shelf * 0.55, 2.55, WZ0 + 0.45); shelf++; e = { mesh: m, kind: "thing" }; }
      kit.tipOn(e.mesh, () => { const now = latest.creations.find((x) => x.name === c.name) || c; return { title: now.name, text: `${now.quality}. ${now.description}` + (now.clock ? (now.clock.running ? " It's going." : " It has stopped and needs tending.") : "") }; });
      e.name = c.name; made.set(c.name, e);
    }
    for (const [name, e] of made) e.mesh.visible = list.some((c) => c.name === name);     // sold or given away: gone
  }

  const pip = kit.sprite(art.pip(), 1.0, 1.375), bubble = kit.sprite(art.bubble(), 0.7, 0.6, false), zzz = kit.sprite(art.zzz(), 0.6, 0.6, false), spark = kit.sprite(art.spark(), 0.35, 0.35, false);
  kit.tipOn(pip, () => ({ title: "Pip", text: `${latest.pip.description || latest.pip.activity}. Feeling ${latest.pip.mood}; energy ${Math.round(latest.pip.energy * 100)}%.` }));

  function update(d) {
    latest = d; plotsFor(d.garden || []); creationsFor(d.creations || []);
    const ripe = (d.garden || []).find((g) => g.state !== "empty");
    bubble.material.map = art.bubble(ripe && /tomato/i.test(ripe.crop) ? "#d8432f" : "#6aa847");
  }
  update(data);

  const gardenWalk = [[1.4, -3.4], [6.2, -3.4], [6.2, -3.4], [1.4, -3.4]];
  const along = (path, k) => { const seg = k * (path.length - 1), i = Math.min(path.length - 2, Math.floor(seg)), f = seg - i; return [path[i][0] + (path[i + 1][0] - path[i][0]) * f, path[i][1] + (path[i + 1][1] - path[i][1]) * f]; };
  kit.every((t) => {
    const pose = poseOf(latest.pip);
    pip.visible = pose !== "away"; bubble.visible = zzz.visible = spark.visible = false; pip.scale.x = 1;
    if (pose === "sit") { pip.position.set(STOOL[0], 1.45, STOOL[1]); kit.frame(pip, 9); bubble.visible = /garden|crop|plot|ripen|pea|tomato/i.test(latest.pip.description) && Math.floor(t / 3) % 3 !== 2; bubble.position.set(STOOL[0] + 0.5, 2.55 + Math.sin(t * 2) * 0.04, STOOL[1] + 0.05); }
    else if (pose === "sleep") { pip.position.set(STOOL[0], 1.45, STOOL[1]); kit.frame(pip, 6); zzz.visible = true; zzz.position.set(STOOL[0] + 0.6, 2.4 + ((t * 0.3) % 0.4), STOOL[1] + 0.05); }
    else if (pose === "work") { pip.position.set(BENCH[0], 0.75, BENCH[1]); const hit = Math.floor(t * 4) % 2; kit.frame(pip, 7 + hit); spark.visible = hit === 1; spark.position.set(-5.9, 1.55, WZ0 + 1.6); }
    else if (pose === "garden") { const k = (t * 0.05) % 1, [x, z] = along(gardenWalk, k), still = k > 0.3 && k < 0.5; pip.position.set(x, 0.72, z); kit.frame(pip, still ? Math.floor(t * 1.6) % 2 : 2 + Math.floor(t * 8) % 4); pip.scale.x = k > 0.5 ? -1 : 1; }
    else if (pose === "idle") { pip.position.set(-4.6, 0.75, WZ0 + 2.9); kit.frame(pip, Math.floor(t * 1.6) % 2); }
    for (const e of made.values()) {
      if (e.kind === "clock") { const c = latest.creations.find((x) => x.name === e.name) || {}; const min = c.clock ? c.clock.minutes + (c.clock.running ? (Date.now() / 1000 - latest.now.ts) / 60 : 0) : 0; e.ck.draw(Math.floor(min), c.clock?.running ? Math.round(Math.sin(t * Math.PI) * 2) : 0); }
      if (e.kind === "walker") { const wk = (Math.sin(t * 0.35 + e.lane) + 1) / 2; e.mesh.position.set(-9.4 + wk * 3.2, 0.42, WZ1 - 1.0 - e.lane * 0.6); e.mesh.scale.x = Math.cos(t * 0.35 + e.lane) >= 0 ? 1 : -1; e.t.offset.x = (Math.floor(t * 6) % 2) / 2; }
    }
    sway.forEach((m) => { m.rotation.z = Math.sin(t * 0.8 + m.userData.sway) * 0.025; });
    water.map.offset.x = (t * 0.03) % 1;
  });
  return { update };
}
