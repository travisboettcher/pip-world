// The parchment map (docs/DESIGN-world-view.md). Drawn in the browser from /world/map: the land is invented from the world seed around
// the engine's own place spots, so it is the same every time; only what Pip has walked is painted, and the sheet grows as Pip goes further.
// A map unit is a minute of Pip's walking (worldmap.py), so the scale bar is in minutes.

const W = 1600, H = 1000, GRID = 4;          // the sheet, in pixels; the land is computed on a coarser grid and painted smooth
const MIN_SPAN = 64, PAD = 16;               // the smallest sheet (in minutes of walking across), and the margin round what Pip knows

/* ---------- seeded noise ---------- */
function hash(x, y, s) { let h = (x * 374761393 + y * 668265263 + s * 2147483647) | 0; h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967295; }
function vnoise(x, y, s) {
  const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi, u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
  const a = hash(xi, yi, s), b = hash(xi + 1, yi, s), c = hash(xi, yi + 1, s), d = hash(xi + 1, yi + 1, s);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}
function fbm(x, y, s, oct = 5) { let t = 0, amp = 0.5, f = 1, norm = 0; for (let i = 0; i < oct; i++) { t += vnoise(x * f, y * f, s + i * 31) * amp; norm += amp; amp *= 0.5; f *= 2.03; } return t / norm; }
function rng(seed) { let s = (seed * 9301 + 49297) % 2147483647 || 1; return () => (s = (s * 16807) % 2147483647) / 2147483647; }
export function keyHash(key) { let h = 2166136261; for (const ch of key) h = Math.imul(h ^ ch.codePointAt(0), 16777619); return h >>> 0; }

/* ---------- the land ---------- */
export function land(data) {
  const s = data.seed, ps = data.places;
  const cx = ps.reduce((a, p) => a + p.x, 0) / ps.length, cy = ps.reduce((a, p) => a + p.y, 0) / ps.length;
  const reach = Math.max(20, ...ps.map((p) => Math.hypot(p.x - cx, p.y - cy)));
  const coasts = ps.filter((p) => p.coastal && Math.hypot(p.x, p.y) > 0.5).map((p) => { const r = Math.hypot(p.x, p.y); return { p, ux: p.x / r, uy: p.y / r }; });
  return {
    height(x, y) {
      const wx = x + (fbm(x / 22, y / 22, s + 7, 3) - 0.5) * 14, wy = y + (fbm(x / 22 + 9, y / 22, s + 8, 3) - 0.5) * 14;   // ragged edges
      let h = fbm(wx / 26, wy / 26, s) - 0.47;
      h += 0.34 * Math.exp(-(((x - cx) / (reach * 1.4)) ** 2 + ((y - cy) / (reach * 1.4)) ** 2));                    // the country Pip lives in
      for (const c of coasts) {                                                     // a place by the water has the water just beyond it
        const dx = x - c.p.x, dy = y - c.p.y, along = dx * c.ux + dy * c.uy, side = Math.abs(dx * c.uy - dy * c.ux), width = 9 + Math.max(0, along) * 0.9;
        if (along > 2) h -= Math.min(0.6, (along - 2) * 0.035) * Math.exp(-(side * side) / (2 * width * width));
      }
      for (const p of ps) { const k = Math.exp(-(((x - p.x) ** 2 + (y - p.y) ** 2) / 30)); h = h * (1 - k) + Math.max(h, p.coastal ? 0.05 : 0.09) * k; }   // every place on land
      return h;
    },
    moisture(x, y) { let m = fbm(x / 18 + 40, y / 18 - 20, s + 11, 4); for (const c of coasts) m += 0.18 * Math.exp(-((x - c.p.x) ** 2 + (y - c.p.y) ** 2) / 120); return m; }
  };
}

/* ---------- the sheet: which part of the world it shows ---------- */
export function frame(data) {
  const known = data.places;
  let x0 = Math.min(0, ...known.map((p) => p.x)) - PAD, x1 = Math.max(0, ...known.map((p) => p.x)) + PAD;
  let y0 = Math.min(0, ...known.map((p) => p.y)) - PAD, y1 = Math.max(0, ...known.map((p) => p.y)) + PAD;
  let w = Math.max(MIN_SPAN, x1 - x0), h = Math.max(MIN_SPAN / 1.6, y1 - y0);
  if (w / h < 1.6) w = h * 1.6; else h = w / 1.6;
  const mx = (x0 + x1) / 2, my = (y0 + y1) / 2;
  x0 = mx - w / 2; x1 = mx + w / 2; y0 = my - h / 2; y1 = my + h / 2;
  return { x0, x1, y0, y1, unit: W / w, toPx: (x, y) => [(x - x0) / w * W, (y1 - y) / h * H], toW: (px, py) => [x0 + px / W * w, y1 - py / H * h] };
}

/* ---------- what Pip has explored: 1 inside, fading to 0 a little beyond ---------- */
export function explored(data) {
  const seen = data.places.filter((p) => p.key === data.home || p.visits > 0);
  return (x, y) => {
    let best = 1e9;
    for (const p of seen) best = Math.min(best, Math.hypot(x - p.x, y - p.y) - (p.key === data.home ? 15 : 8 + Math.min(6, p.visits * 0.5)));
    for (const p of seen) {
      if (p.key === data.home) continue;
      const L = p.x * p.x + p.y * p.y || 1, t = Math.max(0, Math.min(1, (x * p.x + y * p.y) / L));
      best = Math.min(best, Math.hypot(x - t * p.x, y - t * p.y) - 4.5);
    }
    return Math.max(0, Math.min(1, 1 - best / 7));
  };
}

const BIOME = { deep: [104, 135, 140], shallow: [150, 172, 160], beach: [214, 196, 146], marsh: [150, 160, 112], grass: [172, 178, 116],
  forest: [122, 146, 88], hills: [196, 170, 120], peaks: [176, 160, 132], snow: [232, 226, 210] };
const SEASON_TINT = { winter: [0.94, 0.96, 1.04], spring: [0.98, 1.03, 0.98], summer: [1.0, 1.0, 0.97], autumn: [1.06, 0.98, 0.9] };
export function biomeOf(h, m) {
  if (h < 0) return h < -0.06 ? "deep" : "shallow";
  if (h < 0.025 && m < 0.6) return "beach";
  if (h < 0.11 && m > 0.56) return "marsh";
  if (h > 0.46) return h > 0.56 ? "snow" : "peaks";
  if (h > 0.3) return "hills";
  if (m > 0.53) return "forest";
  return "grass";
}

/* ---------- roads: from home, each with its own gentle wander ---------- */
export function road(place, f, seed) {
  const [hx, hy] = f.toPx(0, 0), [tx, ty] = f.toPx(place.x, place.y), len = Math.hypot(tx - hx, ty - hy) || 1, nx = -(ty - hy) / len, ny = (tx - hx) / len;
  const k = keyHash(place.key), sign = k % 2 ? 1 : -1, pts = [];
  for (let i = 0; i <= 60; i++) {
    const t = i / 60, bend = Math.sin(t * Math.PI) * (len * 0.1 * sign + (fbm(t * 6, (k % 997) / 10, seed + 50, 2) - 0.5) * 18);
    pts.push([hx + (tx - hx) * t + nx * bend, hy + (ty - hy) * t + ny * bend]);
  }
  return pts;
}

/* ---------- drawing the sheet ---------- */
export function drawSheet(ctx, data) {
  const f = frame(data), world = land(data), ex = explored(data), gw = W / GRID, gh = H / GRID, seed = data.seed;
  const n = (gw + 1) * (gh + 1), hgt = new Float32Array(n), mst = new Float32Array(n), exp = new Float32Array(n);
  for (let j = 0; j <= gh; j++) for (let i = 0; i <= gw; i++) { const [x, y] = f.toW(i * GRID, j * GRID), k = j * (gw + 1) + i; hgt[k] = world.height(x, y); mst[k] = world.moisture(x, y); exp[k] = ex(x, y); }
  const at = (a, i, j) => a[Math.max(0, Math.min(gh, j)) * (gw + 1) + Math.max(0, Math.min(gw, i))];

  // parchment, at half size, with a few stains
  const pw = W / 2, ph = H / 2, pc = document.createElement("canvas"); pc.width = pw; pc.height = ph;
  const pcx = pc.getContext("2d"), paper = pcx.createImageData(pw, ph), pd = paper.data;
  for (let py = 0; py < ph; py++) for (let px = 0; px < pw; px++) {
    const nn = fbm(px / 70, py / 70, 77, 4), fine = vnoise(px / 1.5, py / 1.5, 5), edge = Math.min(px, py, pw - px, ph - py) / 60;
    const dark = (1 - Math.min(1, edge)) * 0.28 + (nn - 0.5) * 0.16 + (fine - 0.5) * 0.035, o = (py * pw + px) * 4;
    pd[o] = 236 - dark * 120; pd[o + 1] = 222 - dark * 125; pd[o + 2] = 186 - dark * 120; pd[o + 3] = 255;
  }
  pcx.putImageData(paper, 0, 0); ctx.imageSmoothingEnabled = true; ctx.drawImage(pc, 0, 0, W, H);

  // washes, hill-shaded and tinted by the season, only where Pip has been
  const tint = SEASON_TINT[data.now?.season] || [1, 1, 1];
  const wash = document.createElement("canvas"); wash.width = gw; wash.height = gh; const wc = wash.getContext("2d"), wd = wc.createImageData(gw, gh);
  for (let j = 0; j < gh; j++) for (let i = 0; i < gw; i++) {
    const h = at(hgt, i, j), m = at(mst, i, j), e = at(exp, i, j);
    let c = BIOME[biomeOf(h, m)].slice();
    if (h < 0) { const t = Math.min(1, -h / 0.2); c = c.map((v) => v * (1 - t * 0.25)); }
    else { const shade = 1 + (at(hgt, i - 1, j - 1) - at(hgt, i + 1, j + 1)) * 5.5; c = c.map((v, k) => Math.max(0, Math.min(255, v * shade * tint[k]))); }
    const o = (j * gw + i) * 4, wob = 0.82 + vnoise(i / 4, j / 4, 3) * 0.18;
    wd.data[o] = c[0]; wd.data[o + 1] = c[1]; wd.data[o + 2] = c[2]; wd.data[o + 3] = 255 * e * wob * 0.9;
  }
  wc.putImageData(wd, 0, 0);
  ctx.save(); ctx.globalCompositeOperation = "multiply"; ctx.drawImage(wash, 0, 0, W, H); ctx.restore();

  // the coastline and offshore ripples (marching squares), inked where explored
  function contour(level, style, width) {
    ctx.strokeStyle = style; ctx.lineWidth = width; ctx.lineCap = "round"; ctx.beginPath();
    for (let j = 0; j < gh; j++) for (let i = 0; i < gw; i++) {
      if (at(exp, i, j) < 0.35) continue;
      const a = at(hgt, i, j) - level, b = at(hgt, i + 1, j) - level, c = at(hgt, i + 1, j + 1) - level, d = at(hgt, i, j + 1) - level, pts = [];
      if ((a > 0) !== (b > 0)) pts.push([i + a / (a - b), j]);
      if ((b > 0) !== (c > 0)) pts.push([i + 1, j + b / (b - c)]);
      if ((d > 0) !== (c > 0)) pts.push([i + d / (d - c), j + 1]);
      if ((a > 0) !== (d > 0)) pts.push([i, j + a / (a - d)]);
      for (let k = 0; k + 1 < pts.length; k += 2) { ctx.moveTo(pts[k][0] * GRID, pts[k][1] * GRID); ctx.lineTo(pts[k + 1][0] * GRID, pts[k + 1][1] * GRID); }
    }
    ctx.stroke();
  }
  contour(-0.075, "rgba(58,42,28,0.18)", 1); contour(-0.035, "rgba(58,42,28,0.28)", 1); contour(0, "rgba(52,36,22,0.9)", 2.2);

  // glyphs: mountains, hills, trees, marsh tufts, kept clear of the places
  const G = rng(seed + 5), placesPx = data.places.map((p) => f.toPx(p.x, p.y)), marks = [];
  for (let py = 20; py < H - 10; py += 15) for (let px = 10; px < W - 10; px += 15) {
    const jx = px + (G() - 0.5) * 12, jy = py + (G() - 0.5) * 12, i = Math.round(jx / GRID), j = Math.round(jy / GRID), h = at(hgt, i, j), m = at(mst, i, j);
    if (at(exp, i, j) < 0.5 || h < 0 || placesPx.some(([x, y]) => Math.hypot(x - jx, y - jy) < 32)) continue;
    const b = biomeOf(h, m), r = G();
    if ((b === "peaks" || b === "snow") && r < 0.75) marks.push(["mtn", jx, jy, 1 + (h - 0.46) * 4]);
    else if (b === "hills" && r < 0.22) marks.push(["hill", jx, jy, 1]);
    else if (b === "forest" && r < 0.7) marks.push(["tree", jx, jy, 0.8 + G() * 0.5]);
    else if (b === "marsh" && r < 0.45) marks.push(["tuft", jx, jy, 1]);
  }
  marks.sort((a, b) => a[2] - b[2]).forEach(([k, x, y, s]) => glyph(ctx, k, x, y, s, data.now?.season));

  // roads to the places Pip has been, then the places, then Pip
  for (const p of data.places) {
    if (p.key === data.home || !p.visits) continue;
    const pts = road(p, f, seed);
    ctx.strokeStyle = "rgba(92,58,30,0.85)"; ctx.lineWidth = 2; ctx.setLineDash([2, 6]); ctx.lineCap = "round"; ctx.beginPath();
    pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.stroke(); ctx.setLineDash([]);
  }
  const taken = [];                                    // label boxes already placed, so the next one finds a free side
  for (const p of [...data.places].sort((a, b) => (b.key === data.home) - (a.key === data.home))) {
    const [x, y] = f.toPx(p.x, p.y), heard = p.heard_only || (!p.visits && p.key !== data.home), label = p.key === data.home ? "Pip's Workshop" : p.label;
    if (heard) pencilled(ctx, x, y, label); else { icon(ctx, p.kind, x, y); plaque(ctx, x, y, label, taken); }
  }
  // the scale, the compass and the title
  const sx = 70, sy = H - 60, ten = f.unit * 10;
  ctx.strokeStyle = "#3a2a1c"; ctx.fillStyle = "#3a2a1c"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(sx + ten * 3, sy); ctx.stroke();
  for (let i = 0; i <= 3; i++) { ctx.beginPath(); ctx.moveTo(sx + ten * i, sy - 6); ctx.lineTo(sx + ten * i, sy + 6); ctx.stroke(); if (i < 3 && i % 2 === 0) ctx.fillRect(sx + ten * i, sy - 3, ten, 6); }
  ctx.font = "16px 'IM Fell English', Georgia, serif"; ctx.textAlign = "left"; ctx.fillText("minutes of Pip's walking:  10   20   30", sx, sy - 14);
  compass(ctx, W - 120, 120);
  ctx.font = "italic 34px 'IM Fell English', Georgia, serif"; ctx.fillStyle = "rgba(58,42,28,0.8)"; ctx.fillText("The Country round Pip's Workshop", 60, 70);
  ctx.font = "italic 16px 'IM Fell English', Georgia, serif";
  ctx.fillText(`as far as Pip has walked, to ${new Date((data.now?.ts ?? Date.now() / 1000) * 1000).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })}`, 62, 96);
  ctx.font = "italic 22px 'IM Fell English', Georgia, serif"; ctx.fillStyle = "rgba(58,42,28,0.3)"; ctx.textAlign = "center";
  ctx.fillText("here Pip has not been", W - 260, H - 70);
  return f;
}

function glyph(ctx, k, x, y, s, season) {
  ctx.save(); ctx.translate(x, y); ctx.scale(s, s); ctx.strokeStyle = "#3a2a1c"; ctx.lineWidth = 1.1 / s; ctx.lineJoin = "round";
  if (k === "mtn") {
    ctx.fillStyle = "rgba(240,230,205,0.9)"; ctx.beginPath(); ctx.moveTo(-11, 6); ctx.lineTo(-1, -12); ctx.lineTo(10, 6); ctx.closePath(); ctx.fill(); ctx.stroke();
    ctx.fillStyle = "rgba(90,70,50,0.45)"; ctx.beginPath(); ctx.moveTo(-1, -12); ctx.lineTo(10, 6); ctx.lineTo(1, 6); ctx.lineTo(2, -2); ctx.closePath(); ctx.fill();
    ctx.beginPath(); for (let i = 0; i < 4; i++) { ctx.moveTo(-6 + i * 1.6, 5); ctx.lineTo(-3 + i * 1.4, -1 + i); } ctx.stroke();
  } else if (k === "hill") {
    ctx.beginPath(); ctx.moveTo(-9, 4); ctx.quadraticCurveTo(0, -8, 9, 4); ctx.stroke(); ctx.beginPath(); ctx.moveTo(2, -1); ctx.lineTo(4, 3); ctx.moveTo(5, 0); ctx.lineTo(6.5, 3); ctx.stroke();
  } else if (k === "tree") {
    ctx.fillStyle = season === "autumn" ? "rgba(168,110,52,0.85)" : season === "winter" ? "rgba(110,122,96,0.75)" : "rgba(84,110,60,0.85)";
    ctx.beginPath(); ctx.arc(0, -3, 4.2, 0, Math.PI * 2); ctx.fill(); ctx.stroke(); ctx.beginPath(); ctx.moveTo(0, 1); ctx.lineTo(0, 5); ctx.stroke();
  } else {
    ctx.beginPath(); ctx.moveTo(-4, 2); ctx.lineTo(-5, -3); ctx.moveTo(0, 2); ctx.lineTo(0, -4); ctx.moveTo(4, 2); ctx.lineTo(5, -3); ctx.moveTo(-7, 2); ctx.lineTo(7, 2); ctx.stroke();
  }
  ctx.restore();
}

function roundRect(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }
export function labelSpot(x, y, w, h, taken) {
  const spots = [[x - w / 2, y + 18], [x - w / 2, y - 34 - h], [x + 26, y - h / 2], [x - 26 - w, y - h / 2], [x - w / 2, y + 18 + h + 4], [x - w / 2, y - 38 - 2 * h]];
  const free = spots.find(([bx, by]) => !taken.some((t) => bx < t[0] + t[2] + 4 && bx + w + 4 > t[0] && by < t[1] + t[3] + 4 && by + h + 4 > t[1])) ?? spots[0];
  taken.push([free[0], free[1], w, h]);
  return free;
}
function plaque(ctx, x, y, label, taken = []) {
  ctx.font = "19px 'IM Fell English SC', Georgia, serif"; const tw = ctx.measureText(label).width, [bx, by] = labelSpot(x, y, tw + 18, 26, taken);
  ctx.fillStyle = "rgba(48,40,34,0.88)"; roundRect(ctx, bx, by, tw + 18, 26, 4); ctx.fill();
  ctx.strokeStyle = "rgba(230,214,170,0.5)"; ctx.lineWidth = 1; roundRect(ctx, bx + 2, by + 2, tw + 14, 22, 3); ctx.stroke();
  ctx.fillStyle = "#f1e6c8"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(label, bx + (tw + 18) / 2, by + 14); ctx.textBaseline = "alphabetic";
}
function pencilled(ctx, x, y, label) {                 // somewhere Pip has only heard of: a pencilled question, not an inked place
  ctx.save(); ctx.strokeStyle = "rgba(90,74,58,0.6)"; ctx.fillStyle = "rgba(90,74,58,0.7)"; ctx.lineWidth = 1.2; ctx.setLineDash([3, 3]);
  ctx.beginPath(); ctx.arc(x, y, 11, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
  ctx.font = "italic 20px 'IM Fell English', Georgia, serif"; ctx.textAlign = "center"; ctx.fillText("?", x, y + 7);
  ctx.font = "italic 17px 'IM Fell English', Georgia, serif"; ctx.fillText(label, x, y + 32); ctx.restore();
}
function icon(ctx, kind, x, y) {
  ctx.save(); ctx.translate(x, y); ctx.strokeStyle = "#2e2016"; ctx.lineWidth = 1.6; ctx.lineJoin = "round";
  const house = (dx, dy, w, h, roof = "#9a4a32") => { ctx.fillStyle = "#efe2c0"; ctx.fillRect(dx - w / 2, dy - h, w, h); ctx.strokeRect(dx - w / 2, dy - h, w, h); ctx.fillStyle = roof; ctx.beginPath(); ctx.moveTo(dx - w / 2 - 3, dy - h); ctx.lineTo(dx, dy - h - w * 0.6); ctx.lineTo(dx + w / 2 + 3, dy - h); ctx.closePath(); ctx.fill(); ctx.stroke(); };
  ctx.fillStyle = "#efe2c0";
  if (kind === "home") { house(0, 6, 22, 14); ctx.fillStyle = "#c9862a"; ctx.beginPath(); ctx.arc(0, -3, 3, 0, Math.PI * 2); ctx.fill(); ctx.stroke(); for (let i = 0; i < 3; i++) ctx.strokeRect(14 + i * 6, 0, 4, 6); }
  else if (kind === "library") { ctx.fillRect(-16, -12, 32, 18); ctx.strokeRect(-16, -12, 32, 18); for (let i = -12; i <= 12; i += 6) { ctx.beginPath(); ctx.moveTo(i, -12); ctx.lineTo(i, 6); ctx.stroke(); } ctx.fillStyle = "#8c8472"; ctx.beginPath(); ctx.moveTo(-19, -12); ctx.lineTo(0, -22); ctx.lineTo(19, -12); ctx.closePath(); ctx.fill(); ctx.stroke(); }
  else if (kind === "wild") { [[-10, 2], [0, -4], [10, 2], [-4, 8], [6, 9]].forEach(([dx, dy]) => { ctx.fillStyle = "#6f8a4c"; ctx.beginPath(); ctx.moveTo(dx, dy - 14); ctx.lineTo(dx - 6, dy); ctx.lineTo(dx + 6, dy); ctx.closePath(); ctx.fill(); ctx.stroke(); }); }
  else if (kind === "yard") { ctx.fillStyle = "#b9a78a"; [[-12, 0, 10, 7], [-3, -6, 12, 12], [9, 0, 8, 6]].forEach(([dx, dy, w, h]) => { ctx.fillRect(dx, dy, w, h); ctx.strokeRect(dx, dy, w, h); }); ctx.beginPath(); ctx.arc(3, 0, 4, 0, Math.PI * 2); ctx.stroke(); }
  else if (kind === "neighbor") { house(4, 6, 18, 11, "#5b6a74"); ctx.fillStyle = "#f4efe2"; ctx.fillRect(-16, -12, 7, 18); ctx.strokeRect(-16, -12, 7, 18); ctx.fillStyle = "#c9862a"; ctx.fillRect(-15, -16, 5, 4); ctx.strokeRect(-15, -16, 5, 4); }
  else if (kind === "shop") { house(0, 6, 20, 13, "#7a5236"); ctx.fillStyle = "#d9a441"; ctx.fillRect(-11, -2, 22, 3); ctx.strokeRect(-11, -2, 22, 3); }
  else if (kind === "market") { [[-12, "#b5402f"], [0, "#d9a441"], [12, "#6f9a8a"]].forEach(([dx, c]) => { ctx.fillStyle = c; ctx.beginPath(); ctx.moveTo(dx - 7, -4); ctx.lineTo(dx, -14); ctx.lineTo(dx + 7, -4); ctx.closePath(); ctx.fill(); ctx.stroke(); ctx.beginPath(); ctx.moveTo(dx - 6, -4); ctx.lineTo(dx - 6, 6); ctx.moveTo(dx + 6, -4); ctx.lineTo(dx + 6, 6); ctx.stroke(); }); }
  else { ctx.beginPath(); ctx.moveTo(-10, 6); ctx.lineTo(0, -12); ctx.lineTo(10, 6); ctx.closePath(); ctx.fill(); ctx.stroke(); ctx.beginPath(); ctx.arc(0, -16, 3, 0, Math.PI * 2); ctx.stroke(); }  // a sight
  ctx.restore();
}
function compass(ctx, x, y) {
  ctx.save(); ctx.translate(x, y); ctx.strokeStyle = "#3a2a1c"; ctx.lineWidth = 1.3;
  ctx.beginPath(); ctx.arc(0, 0, 44, 0, Math.PI * 2); ctx.stroke(); ctx.beginPath(); ctx.arc(0, 0, 38, 0, Math.PI * 2); ctx.stroke();
  for (let i = 0; i < 8; i++) { const a = i * Math.PI / 4, long = i % 2 === 0 ? 52 : 30; ctx.fillStyle = i % 2 === 0 ? "#3a2a1c" : "rgba(58,42,28,0.5)"; ctx.beginPath(); ctx.moveTo(Math.sin(a) * long, -Math.cos(a) * long); ctx.lineTo(Math.sin(a + 0.35) * 8, -Math.cos(a + 0.35) * 8); ctx.lineTo(0, 0); ctx.closePath(); ctx.fill(); }
  ctx.font = "20px 'IM Fell English SC', Georgia, serif"; ctx.fillStyle = "#3a2a1c"; ctx.textAlign = "center"; ctx.fillText("N", 0, -58); ctx.restore();
}

/* ---------- Pip: a flag where it is, or moving along the road while it walks ---------- */
export function pipAt(data, f, now = Date.now() / 1000) {
  const w = data.pip.walking, byKey = Object.fromEntries(data.places.map((p) => [p.key, p]));
  if (!w || !byKey[w.to] || !byKey[w.from]) { const p = byKey[data.pip.at] || byKey[data.home]; return { xy: f.toPx(p.x, p.y), walking: null }; }
  const k = w.ends_at > w.started_at ? Math.max(0, Math.min(1, (now - w.started_at) / (w.ends_at - w.started_at))) : w.progress;
  const out = w.from === data.home ? road(byKey[w.to], f, data.seed) : w.to === data.home ? road(byKey[w.from], f, data.seed).slice().reverse()
    : [f.toPx(byKey[w.from].x, byKey[w.from].y), f.toPx(byKey[w.to].x, byKey[w.to].y)];
  const seg = k * (out.length - 1), i = Math.min(out.length - 2, Math.floor(seg)), t = seg - i;
  return { xy: [out[i][0] + (out[i + 1][0] - out[i][0]) * t, out[i][1] + (out[i + 1][1] - out[i][1]) * t], walking: { ...w, k, path: out } };
}
export function drawPip(ctx, data, f, now) {
  ctx.clearRect(0, 0, W, H);
  const { xy: [x, y], walking } = pipAt(data, f, now);
  if (walking) { ctx.strokeStyle = "rgba(201,134,42,0.9)"; ctx.lineWidth = 3; ctx.setLineDash([6, 6]); ctx.beginPath(); walking.path.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py))); ctx.stroke(); ctx.setLineDash([]); }
  ctx.fillStyle = "#c9862a"; ctx.strokeStyle = "#3a2a1c"; ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.moveTo(x + 2, y - 8); ctx.lineTo(x + 2, y - 34); ctx.lineTo(x + 20, y - 27); ctx.lineTo(x + 2, y - 20); ctx.fill(); ctx.stroke();
  ctx.font = "italic 16px 'IM Fell English', Georgia, serif"; ctx.fillStyle = "#3a2a1c"; ctx.textAlign = "left";
  ctx.fillText(walking ? "Pip, on the way" : "Pip is here", x + 24, y - 24);
}

/* ---------- the widget: a sheet that pans and zooms, with Pip on top ---------- */
export class WorldMap {
  constructor(host, { onPlace } = {}) {
    this.host = host; this.onPlace = onPlace; this.view = { s: 1, x: 0, y: 0 }; this.data = null; this.sig = "";
    this.inner = document.createElement("div"); this.inner.className = "wm-inner";
    this.sheet = document.createElement("canvas"); this.pipLayer = document.createElement("canvas");
    for (const c of [this.sheet, this.pipLayer]) { c.width = W; c.height = H; this.inner.append(c); }
    this.sheet.setAttribute("role", "img"); this.busy = document.createElement("p"); this.busy.className = "wm-busy"; this.busy.textContent = "Inking the map…";
    host.replaceChildren(this.inner, this.busy); host.classList.add("wm");
    this._wire();
    new ResizeObserver(() => this._apply()).observe(host);
  }
  set(data) {
    this.data = data;
    const sig = JSON.stringify([data.seed, data.now?.season, data.places.map((p) => [p.key, p.x, p.y, p.visits > 0, p.heard_only, p.coastal, p.label, Math.min(12, p.visits)])]);
    const go = () => {
      if (sig !== this.sig) { this.frame = drawSheet(this.sheet.getContext("2d"), data); this.sig = sig; }
      this.busy.hidden = true; this.sheet.setAttribute("aria-label", `Map of the country round Pip's workshop. ${data.places.filter((p) => p.visits).length} places visited.`);
      if (!this.opened) { this.opened = true; if (this.host.clientWidth < 600) this.centreOnPip(); }   // a phone opens close in, on Pip
      this._pip(); clearInterval(this.tick); if (data.pip.walking) this.tick = setInterval(() => this._pip(), 1000);
    };
    if (sig === this.sig) go(); else { this.busy.hidden = false; (document.fonts?.ready ?? Promise.resolve()).then(() => setTimeout(go, 20)); }
  }
  centreOnPip() { if (!this.frame) return; const [x, y] = pipAt(this.data, this.frame).xy, r = this.host.getBoundingClientRect(); this.view.s = Math.max(this.view.s, 2.4); this.view.x = r.width / 2 - x / W * r.width * this.view.s; this.view.y = r.height / 2 - y / H * r.height * this.view.s; this._apply(); }
  zoom(f) { const r = this.host.getBoundingClientRect(); this._zoomAt(r.left + r.width / 2, r.top + r.height / 2, f); this._apply(); }
  _pip() { if (this.frame) drawPip(this.pipLayer.getContext("2d"), this.data, this.frame); }
  _apply() { const r = this.host.getBoundingClientRect(), v = this.view; v.s = Math.max(1, Math.min(5, v.s)); v.x = Math.min(0, Math.max(r.width - r.width * v.s, v.x)); v.y = Math.min(0, Math.max(r.height - r.height * v.s, v.y)); this.inner.style.transform = `translate(${v.x}px, ${v.y}px) scale(${v.s})`; }
  _zoomAt(cx, cy, f) { const r = this.host.getBoundingClientRect(), px = cx - r.left, py = cy - r.top, ns = Math.max(1, Math.min(5, this.view.s * f)), k = ns / this.view.s; this.view.x = px - (px - this.view.x) * k; this.view.y = py - (py - this.view.y) * k; this.view.s = ns; }
  _wire() {
    const pts = new Map(); let pinch = 0, moved = 0;
    const el = this.inner;
    el.addEventListener("pointerdown", (e) => { el.setPointerCapture(e.pointerId); pts.set(e.pointerId, [e.clientX, e.clientY]); moved = 0; });
    el.addEventListener("pointermove", (e) => {
      if (!pts.has(e.pointerId)) return; const [ox, oy] = pts.get(e.pointerId); pts.set(e.pointerId, [e.clientX, e.clientY]); moved += Math.abs(e.clientX - ox) + Math.abs(e.clientY - oy);
      if (pts.size === 1) { this.view.x += e.clientX - ox; this.view.y += e.clientY - oy; }
      else if (pts.size === 2) { const [a, b] = [...pts.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]); if (pinch) this._zoomAt((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, d / pinch); pinch = d; }
      this._apply();
    });
    const end = (e) => { if (pts.size === 1 && moved < 6) this._click(e); pts.delete(e.pointerId); pinch = 0; };
    el.addEventListener("pointerup", end); el.addEventListener("pointercancel", (e) => { pts.delete(e.pointerId); pinch = 0; });
    this.host.addEventListener("wheel", (e) => { e.preventDefault(); this._zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * 0.0015)); this._apply(); }, { passive: false });
  }
  _click(e) {
    if (!this.frame || !this.onPlace) return;
    const r = this.sheet.getBoundingClientRect(), x = (e.clientX - r.left) / r.width * W, y = (e.clientY - r.top) / r.height * H;
    let best = null, bestD = 40;
    for (const p of this.data.places) { const [px, py] = this.frame.toPx(p.x, p.y), d = Math.hypot(px - x, py - (y - 12)); if (d < bestD) { best = p; bestD = d; } }
    if (best) this.onPlace(best);
  }
}
