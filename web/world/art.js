// The world view's art (docs/DESIGN-world-view.md): every texture and sprite is drawn here in code, pixel by pixel, so there are no assets
// to fetch or license. A later art pass can swap a sprite sheet in behind these same names.

export function rnd(seed) { let s = seed % 2147483647 || 1; return () => (s = (s * 16807) % 2147483647) / 2147483647; }
export function hashStr(s) { let h = 2166136261; for (const ch of String(s)) h = Math.imul(h ^ ch.codePointAt(0), 16777619); return h >>> 0; }

export function makeArt(THREE) {
  function canvasTex(c, repeat = [1, 1]) {
    const t = new THREE.CanvasTexture(c); t.magFilter = t.minFilter = THREE.NearestFilter; t.generateMipmaps = false;
    t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(...repeat); t.encoding = THREE.sRGBEncoding; return t;
  }
  function tex(w, h, draw, repeat) { const c = document.createElement("canvas"); c.width = w; c.height = h; const g = c.getContext("2d"); draw((x, y, ww, hh, col) => { g.fillStyle = col; g.fillRect(x, y, ww, hh); }, g, w, h); return canvasTex(c, repeat); }
  const shade = (hex, k) => { const c = new THREE.Color(hex); c.multiplyScalar(k); return "#" + c.getHexString(); };
  function speckle(px, w, h, base, cols, n, seed) { const r = rnd(seed); px(0, 0, w, h, base); for (let i = 0; i < n; i++) px(Math.floor(r() * w), Math.floor(r() * h), 1, 1, cols[Math.floor(r() * cols.length)]); }
  function sprite(w, h, frames, drawFrame) {
    const c = document.createElement("canvas"); c.width = w * frames; c.height = h; const g = c.getContext("2d");
    for (let f = 0; f < frames; f++) drawFrame((x, y, ww, hh, col) => { g.fillStyle = col; g.fillRect(f * w + x, y, ww, hh); }, f);
    const t = canvasTex(c); t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping; t.repeat.set(1 / frames, 1); t.userData = { frames }; return t;
  }
  const GRASS = { spring: "#64983f", summer: "#5f8f3e", autumn: "#6e8240", winter: "#7d8a6a" };
  const LEAF = { spring: "#5a9a3a", summer: "#4f8a34", autumn: "#b8742e", winter: "#6f7a5e" };

  const T = {
    grass: (rep, season) => { const b = GRASS[season] || GRASS.summer; return tex(16, 16, (px, g, w, h) => { speckle(px, w, h, b, [shade(b, 1.12), shade(b, 0.85), shade(b, 1.3), shade(b, 0.9)], 70, 3); const r = rnd(9); for (let i = 0; i < 6; i++) px(Math.floor(r() * 15), Math.floor(r() * 14), 1, 2, shade(b, 1.45)); }, rep); },
    soil: (rep) => tex(16, 16, (px, g, w, h) => { speckle(px, w, h, "#5a3b24", ["#4a3020", "#6b4529", "#3e281a"], 50, 7); for (let y = 2; y < 16; y += 5) px(0, y, 16, 1, "#3e281a"); }, rep),
    cliff: (rep, season) => { const top = GRASS[season] || GRASS.summer; return tex(16, 16, (px, g, w, h) => { speckle(px, w, h, "#7a5a3a", ["#6b4d31", "#8a6a45", "#5c4129"], 60, 11); for (let y = 5; y < 16; y += 5) px(0, y, 16, 1, "#5c4129"); const r = rnd(4); for (let i = 0; i < 3; i++) { const x = Math.floor(r() * 13), y = 3 + Math.floor(r() * 11); px(x, y, 3, 2, "#9a9488"); px(x, y, 3, 1, "#b8b2a4"); } px(0, 0, 16, 2, top); px(0, 2, 16, 1, shade(top, 0.8)); }, rep); },
    plaster: (rep) => tex(32, 32, (px, g, w, h) => { speckle(px, w, h, "#e6dbc0", ["#ddd0b2", "#efe6cf", "#d4c6a6"], 90, 13); const beam = "#4a2f1f"; px(0, 0, 32, 3, beam); px(0, 29, 32, 3, beam); px(0, 0, 3, 32, beam); px(29, 0, 3, 32, beam); px(14, 0, 3, 32, beam); for (let i = 0; i < 12; i++) { px(3 + i, 3 + Math.floor(i * 2.2), 2, 2, beam); px(28 - i, 3 + Math.floor(i * 2.2), 2, 2, beam); } px(0, 0, 32, 1, "#6b4529"); }, rep),
    inner: (rep) => tex(16, 16, (px, g, w, h) => { speckle(px, w, h, "#d8c8a4", ["#cdbb94", "#e2d4b2"], 40, 15); px(0, 15, 16, 1, "#b8a47e"); }, rep),
    thatch: (rep) => tex(16, 16, (px) => { px(0, 0, 16, 16, "#b8913f"); const r = rnd(17); for (let y = 0; y < 16; y += 4) { const off = (y / 4) % 2 ? 2 : 0; for (let x = 0; x < 16; x += 4) px((x + off) % 16, y, 1, 4, "#8f6c2c"); px(0, y + 3, 16, 1, "#7a5a24"); } for (let i = 0; i < 40; i++) px(Math.floor(r() * 16), Math.floor(r() * 16), 1, 1, r() > 0.5 ? "#d8b65e" : "#a07c34"); }, rep),
    planks: (rep, base = "#7a5236") => tex(16, 16, (px) => { px(0, 0, 16, 16, base); for (let x = 0; x < 16; x += 4) { px(x, 0, 1, 16, shade(base, 0.6)); px(x + 1, 0, 1, 16, shade(base, 1.18)); } const r = rnd(21); for (let i = 0; i < 6; i++) px(Math.floor(r() * 16), Math.floor(r() * 16), 1, 2, shade(base, 0.75)); }, rep),
    floor: (rep) => tex(16, 16, (px) => { px(0, 0, 16, 16, "#8a6440"); for (let y = 0; y < 16; y += 4) { px(0, y, 16, 1, "#5e4028"); px(((y / 4) % 2) * 8 + 3, y, 1, 4, "#5e4028"); } }, rep),
    stone: (rep) => tex(16, 16, (px) => { px(0, 0, 16, 16, "#5e5a54"); [[0, 0, 7, 5], [8, 0, 8, 5], [0, 6, 4, 5], [5, 6, 7, 5], [13, 6, 3, 5], [0, 12, 9, 4], [10, 12, 6, 4]].forEach(([x, y, ww, hh], i) => { px(x, y, ww - 1, hh - 1, ["#9a9488", "#8a857a", "#a6a094"][i % 3]); px(x, y, ww - 1, 1, "#b8b2a4"); }); }, rep),
    cobble: (rep) => tex(16, 16, (px) => { px(0, 0, 16, 16, "#6b6458"); const r = rnd(29); for (let y = 0; y < 16; y += 4) for (let x = (y / 4) % 2 ? -2 : 0; x < 16; x += 4) { px(x + 1, y + 1, 3, 3, ["#a39a88", "#958c7a", "#b0a894"][Math.floor(r() * 3)]); px(x + 1, y + 1, 3, 1, "#c4bca8"); } }, rep),
    leaves: (rep, season, base) => { const b = base || LEAF[season] || LEAF.summer; return tex(16, 16, (px, g, w, h) => speckle(px, w, h, b, [shade(b, 0.7), shade(b, 1.25), shade(b, 0.85), shade(b, 1.4)], 120, 33), rep); },
    water: (rep) => tex(16, 16, (px, g, w, h) => { speckle(px, w, h, "#3f7a96", ["#4b8aa6", "#376c86"], 30, 41); px(2, 4, 4, 1, "#8cc4d8"); px(9, 10, 5, 1, "#8cc4d8"); px(12, 2, 3, 1, "#a8d8e6"); }, rep),
    door: () => tex(16, 24, (px) => { px(0, 0, 16, 24, "#4a2f1f"); px(1, 1, 14, 23, "#9a6a8a"); for (let x = 1; x < 15; x += 3) px(x, 1, 1, 23, "#7a4e6c"); px(1, 8, 14, 1, "#5a3a50"); px(1, 16, 14, 1, "#5a3a50"); px(11, 12, 2, 2, "#e8c060"); }),
    window: (lit) => tex(12, 12, (px) => { px(0, 0, 12, 12, "#4a2f1f"); const a = lit ? "#ffcf7a" : "#26394a", b = lit ? "#ffe2a8" : "#3a5468"; px(1, 1, 10, 10, a); px(5, 1, 2, 10, "#4a2f1f"); px(1, 5, 10, 2, "#4a2f1f"); px(2, 2, 2, 2, b); px(8, 8, 2, 1, b); })
  };

  // Pip: 0-1 idle, 2-5 walk, 6 asleep, 7-8 hammering, 9 sitting
  const pip = () => sprite(16, 22, 10, (px, f) => {
    const bob = (f === 1 || f === 3 || f === 5) ? 1 : 0, y0 = 2 + bob + (f === 9 ? 2 : 0), sleep = f === 6, glow = "#f2b45c";
    px(7, y0 - 2, 1, 3, "#4d5c6c"); px(6, y0 - 4, 3, 2, sleep ? "#a8762a" : glow); px(7, y0 - 4, 1, 1, sleep ? "#a8762a" : "#fff2c4");
    px(3, y0 + 1, 10, 1, "#2a3440"); px(2, y0 + 2, 12, 7, "#2a3440"); px(3, y0 + 2, 10, 6, "#a9bccf"); px(3, y0 + 7, 10, 1, "#7f93a8"); px(3, y0 + 2, 10, 1, "#c8d6e4");
    if (sleep) px(5, y0 + 5, 6, 1, "#1d2421"); else { px(4, y0 + 4, 8, 3, "#1d2421"); px(5, y0 + 4, 2, 2, "#9fe0ff"); px(9, y0 + 4, 2, 2, "#9fe0ff"); }
    px(3, y0 + 9, 10, 7, "#2a3440"); px(4, y0 + 9, 8, 6, "#7f93a8"); px(4, y0 + 9, 8, 1, "#9fb3c8"); px(7, y0 + 11, 2, 2, glow);
    px(2, y0 + 10, 2, 4, "#5d6f82");
    if (f === 7) { px(12, y0 + 5, 2, 5, "#5d6f82"); px(11, y0 + 3, 5, 2, "#b8b8b8"); } else if (f === 8) { px(12, y0 + 10, 3, 2, "#5d6f82"); px(14, y0 + 9, 2, 5, "#b8b8b8"); } else px(12, y0 + 10, 2, 4, "#5d6f82");
    if (f === 9) { px(4, 19, 3, 2, "#4d5c6c"); px(9, 19, 3, 2, "#4d5c6c"); return; }
    const step = f >= 2 && f <= 5 ? [0, 1, 0, -1][f - 2] : 0;
    px(5, y0 + 15 + Math.max(0, step), 2, 3 - Math.max(0, step), "#4d5c6c"); px(9, y0 + 15 + Math.max(0, -step), 2, 3 - Math.max(0, -step), "#4d5c6c"); px(4, 20, 3, 1, "#2a3440"); px(9, 20, 3, 1, "#2a3440");
  });
  const walker = () => sprite(14, 10, 2, (px, f) => { px(2, 1, 10, 6, "#8a6a2a"); px(3, 1, 8, 5, "#c9a24a"); px(3, 1, 8, 1, "#f3dc8e"); px(9, 2, 2, 2, "#ffe9a8"); px(3 + f, 7, 2, 3 - f, "#6b4f1f"); px(9 - f, 7, 2, 2 + f, "#6b4f1f"); });
  const QUALITY = { rough: "#9a7a3a", sound: "#b8923e", fine: "#c9a24a", masterwork: "#e0b84e" };
  const contraption = (quality, seed) => sprite(12, 12, 1, (px) => { const b = QUALITY[quality] || QUALITY.sound, r = rnd(seed); px(1, 4, 10, 7, shade(b, 0.7)); px(2, 4, 8, 6, b); px(2, 4, 8, 1, shade(b, 1.3)); px(3 + Math.floor(r() * 4), 1, 3, 3, shade(b, 1.1)); px(4 + Math.floor(r() * 3), 6, 2, 2, "#3a2a1c"); px(1, 11, 10, 1, "#3a2a1c"); });
  const bubble = (fruit = "#6aa847") => sprite(14, 12, 1, (px) => { px(1, 0, 12, 8, "#f5f1d7"); px(0, 1, 14, 6, "#f5f1d7"); px(5, 8, 3, 2, "#f5f1d7"); px(4, 10, 2, 2, "#f5f1d7"); px(3, 3, 8, 3, fruit); px(4, 4, 2, 1, "#f5f1d7"); px(7, 4, 2, 1, "#f5f1d7"); });
  const zzz = () => sprite(12, 12, 1, (px) => { [[0, 8], [4, 4], [8, 0]].forEach(([x, y]) => { px(x, y, 4, 1, "#cfe6ff"); px(x + 2, y + 1, 1, 1, "#cfe6ff"); px(x + 1, y + 2, 1, 1, "#cfe6ff"); px(x, y + 3, 4, 1, "#cfe6ff"); }); });
  const spark = () => sprite(8, 8, 1, (px) => { px(3, 0, 2, 8, "#ffd27a"); px(0, 3, 8, 2, "#ffd27a"); px(3, 3, 2, 2, "#fff6d0"); });
  const flower = () => sprite(8, 8, 4, (px, f) => { if (f === 3) { px(1, 2, 1, 6, "#6fa047"); px(3, 0, 1, 8, "#5f9a3e"); px(5, 3, 1, 5, "#7fb04f"); px(6, 1, 1, 7, "#5f9a3e"); return; } const c = ["#e86a8a", "#f2d45c", "#9a8ae8"][f]; px(3, 4, 1, 4, "#4f7d34"); px(2, 1, 3, 3, c); px(3, 2, 1, 1, "#fff2c4"); px(1, 6, 2, 1, "#5f9a3e"); });
  // a crop at its growth: peas climb canes, tomatoes bush and redden, anything else is a leafy plant with fruit in a colour of its own
  function crop(name, p, ripe) {
    const n = String(name).toLowerCase(), fruit = ["#d8432f", "#e0782a", "#e8c040", "#9a4a8a", "#c8d860", "#e86a8a"][hashStr(n) % 6];
    return sprite(16, 20, 1, (px) => {
      const hgt = Math.round(3 + Math.min(1, p) * 15);
      if (p < 0.1) { px(7, 17, 2, 3, "#6fa047"); return; }
      if (n.includes("pea") || n.includes("bean")) {
        px(3, 20 - hgt - 1, 1, hgt + 1, "#8a6a45"); px(12, 20 - hgt - 1, 1, hgt + 1, "#8a6a45");
        for (let i = 0; i < hgt; i++) { px(5 + (i % 2), 19 - i, 2, 1, "#5f9a3e"); px(9 - (i % 2), 19 - i, 2, 1, "#6aa847"); if (i % 3 === 1) { px(4, 19 - i, 2, 1, "#8cc06a"); px(10, 19 - i, 2, 1, "#8cc06a"); } }
        if (p > 0.6 || ripe) for (let i = 4; i < hgt; i += 4) px(7, 19 - i, 1, 3, "#b9e08e");
      } else {
        for (let r = 0; r < hgt; r++) { const ww = Math.max(2, Math.round((5 + p * 6) * Math.sin((r / hgt) * Math.PI)) + 2); px(8 - Math.floor(ww / 2), 19 - r, ww, 1, r % 3 ? "#4e8a36" : "#5f9a3e"); }
        const col = n.includes("tomato") ? "#d8432f" : fruit;
        if (p > 0.35 || ripe) [[5, 14], [10, 12], [7, 9], [11, 16]].slice(0, ripe ? 4 : Math.round(p * 4)).forEach(([x, y]) => { px(x, y, 2, 2, ripe || p > 0.85 ? col : "#a8c04a"); px(x, y, 1, 1, "#fff2c4"); });
      }
    });
  }
  // the Gear Clock (or any timekeeper): a live sprite whose hands show its own face and whose pendulum swings while it runs
  function clock() {
    const c = document.createElement("canvas"); c.width = 16; c.height = 28; const t = canvasTex(c); t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
    const draw = (min, swing) => {
      const g = c.getContext("2d"), px = (x, y, w, h, col) => { g.fillStyle = col; g.fillRect(x, y, w, h); };
      g.clearRect(0, 0, 16, 28); px(1, 0, 14, 28, "#4a2f1f"); px(2, 1, 12, 26, "#6f4c31"); px(3, 2, 10, 10, "#c9a24a"); px(4, 3, 8, 8, "#e8d7a6");
      const ha = ((min / 720) % 1) * Math.PI * 2, ma = ((min % 60) / 60) * Math.PI * 2;
      for (let r = 0; r < 3; r++) px(7 + Math.round(Math.sin(ha) * r), 6 - Math.round(Math.cos(ha) * r), 1, 1, "#3b2a21");
      for (let r = 0; r < 4; r++) px(7 + Math.round(Math.sin(ma) * r), 6 - Math.round(Math.cos(ma) * r), 1, 1, "#1d2421");
      px(7, 13, 1, 9, "#3b2a21"); px(6 + swing, 21, 3, 3, "#c9a24a"); px(6 + swing, 21, 3, 1, "#f3dc8e"); t.needsUpdate = true;
    };
    return { texture: t, draw };
  }
  const dot = () => tex(8, 8, (px, g) => { const gr = g.createRadialGradient(4, 4, 0, 4, 4, 4); gr.addColorStop(0, "rgba(255,255,255,1)"); gr.addColorStop(1, "rgba(255,255,255,0)"); g.fillStyle = gr; g.fillRect(0, 0, 8, 8); });
  return { T, tex, sprite, shade, pip, walker, contraption, bubble, zzz, spark, flower, crop, clock, dot, LEAF, GRASS };
}
