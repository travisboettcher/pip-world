// The scene kit (docs/DESIGN-world-view.md): the HD-2D look every place's scene shares. A fixed orthographic camera, the whole frame drawn
// at 512 x 288 and scaled up with crisp pixels, sprites that face the camera and cast shadows, sun and sky from the time of day, the
// weather and the season, lamps that come up at dusk, and a gentle post pass: glow only on real lights, a little depth blur, a warm grade.

const RES = [512, 288], VIEW_W = 26;
const VENDOR = ["three.min.js", "CopyShader.js", "LuminosityHighPassShader.js", "EffectComposer.js", "RenderPass.js", "ShaderPass.js", "UnrealBloomPass.js"];
let loading = null;

export function loadThree(base = "vendor/three/") {   // three.js is vendored (web/vendor/three, MIT) and loaded only when a scene is first shown
  loading ??= VENDOR.reduce((p, f) => p.then(() => new Promise((ok, fail) => {
    const s = document.createElement("script"); s.src = base + f; s.onload = ok; s.onerror = () => fail(new Error(`couldn't load ${f}`)); document.head.append(s);
  })), Promise.resolve()).then(() => window.THREE);
  return loading;
}

const RAIN = ["rainy", "pouring", "lightning-rainy", "lightning"], SNOW = ["snowy", "snowy-rainy", "hail"], GREY = ["cloudy", "fog", "windy", "windy-variant", "exceptional"];

export class Kit {
  constructor(host, THREE, tip) {
    this.THREE = THREE; this.host = host; this.tip = tip; this.hits = []; this.lamps = []; this.updaters = [];
    const r = this.renderer = new THREE.WebGLRenderer({ antialias: false });
    r.setPixelRatio(1); r.setSize(RES[0], RES[1], false); r.outputEncoding = THREE.sRGBEncoding; r.shadowMap.enabled = true; r.shadowMap.type = THREE.PCFShadowMap;
    r.domElement.className = "scene-canvas"; host.prepend(r.domElement);
    this.scene = new THREE.Scene(); this.scene.fog = new THREE.Fog(0x9fb0c0, 30, 60);
    const vh = VIEW_W * RES[1] / RES[0];
    this.camera = new THREE.OrthographicCamera(-VIEW_W / 2, VIEW_W / 2, vh / 2, -vh / 2, 0.1, 120);
    this.camera.position.set(0, 13, 22); this.camera.lookAt(0, 0.2, -1.5);
    this.hemi = new THREE.HemisphereLight(0xbfd6ff, 0x5a5034, 0.5); this.scene.add(this.hemi);
    const sun = this.sun = new THREE.DirectionalLight(0xfff0d8, 1.4); sun.castShadow = true; sun.shadow.mapSize.set(1024, 1024); sun.shadow.bias = -0.0015;
    Object.assign(sun.shadow.camera, { left: -18, right: 18, top: 18, bottom: -18, near: 1, far: 90 }); this.scene.add(sun);
    this._motes(); this._weather(); this._post(); this._tips();
    this.running = true; this.visible = true; this.clock = new THREE.Clock(); this.last = 0;
    new IntersectionObserver(([e]) => { this.visible = e.isIntersecting; }).observe(host);
    this.reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const loop = () => { if (!this.running) return; requestAnimationFrame(loop); this._frame(); };
    requestAnimationFrame(loop);
  }

  /* building blocks */
  mat(map, o = {}) { return new this.THREE.MeshStandardMaterial({ map, roughness: 0.95, metalness: 0, ...o }); }
  box(w, h, d, mat, x, y, z) { const m = new this.THREE.Mesh(new this.THREE.BoxGeometry(w, h, d), mat); m.position.set(x, y, z); m.castShadow = m.receiveShadow = true; this.scene.add(m); return m; }
  boxTS(w, h, d, top, side, x, y, z) { return this.box(w, h, d, [side, side, top, side, side, side], x, y, z); }
  hitbox(w, h, d, x, y, z) {                           // an invisible box for a tooltip: never drawn, never in the depth buffer, casts no shadow
    const m = new this.THREE.Mesh(new this.THREE.BoxGeometry(w, h, d), new this.THREE.MeshBasicMaterial({ colorWrite: false, depthWrite: false })); m.position.set(x, y, z); this.scene.add(m); return m;
  }
  plane(w, h, mat, x, y, z) { const m = new this.THREE.Mesh(new this.THREE.PlaneGeometry(w, h), mat); m.position.set(x, y, z); m.receiveShadow = true; this.scene.add(m); return m; }
  sprite(t, w, h, shadow = true) {
    const T = this.THREE, m = new T.Mesh(new T.PlaneGeometry(w, h), new T.MeshStandardMaterial({ map: t, transparent: true, alphaTest: 0.5, side: T.DoubleSide, roughness: 1 }));
    m.castShadow = shadow; if (shadow) m.customDepthMaterial = new T.MeshDepthMaterial({ depthPacking: T.RGBADepthPacking, map: t, alphaTest: 0.5 });
    m.quaternion.copy(this.camera.quaternion); this.scene.add(m); return m;
  }
  frame(mesh, i) { const t = mesh.material.map; t.offset.x = i / t.userData.frames; }
  tipOn(o, title, text) { o.userData.tip = typeof title === "function" ? title : () => ({ title, text }); this.hits.push(o); return o; }
  lamp(mesh, light, strength = 1) { this.lamps.push({ mesh, light, strength }); return mesh; }
  every(fn) { this.updaters.push(fn); }
  palette(name) { this.tint = new this.THREE.Color({ warm: 0xffe8cc, cool: 0xdde8ff, earth: 0xf0dcc0, moss: 0xe0f0d0, rose: 0xffe0e4, sand: 0xfff0d0, slate: 0xe0e4ea, honey: 0xffe4b0 }[name] || 0xffffff); }

  /* time, weather and season */
  setMoment({ minutes, weather, season }) {
    const T = this.THREE, h = minutes / 60, dayT = Math.max(0, Math.min(1, (h - 6) / 13.5)), elev = Math.sin(dayT * Math.PI), up = h > 6 && h < 19.5;
    const grey = GREY.includes(weather) || RAIN.includes(weather) || SNOW.includes(weather);
    const duskness = up ? Math.max(0, 1 - elev * 2.1) : 0; this.dark = up ? Math.max(0, duskness - 0.45) / 0.55 : 1;
    if (grey && up) this.dark = Math.max(this.dark, 0.25);
    const sky = new T.Color(0x86b4dc).lerp(new T.Color(0xe39a6a), duskness * (grey ? 0.3 : 0.8)); if (!up) sky.set(0x0b1222);
    if (grey && up) sky.lerp(new T.Color(0x9aa4ae), 0.6);
    if (season === "winter" && up) sky.lerp(new T.Color(0xc8d4e0), 0.2);
    this.scene.background = sky; this.scene.fog.color.copy(sky); this.scene.fog.near = weather === "fog" ? 10 : 30; this.scene.fog.far = weather === "fog" ? 34 : 60;
    const az = (dayT - 0.5) * Math.PI * 0.9;
    this.sun.position.set(-Math.sin(az) * 28 + 4, up ? 8 + elev * 26 : 22, 16);
    this.sun.intensity = (up ? 0.55 + elev * 1.15 : 0.18) * (grey ? 0.45 : 1); this.sun.color.set(up ? (duskness > 0.3 && !grey ? 0xffa060 : 0xfff2dc) : 0x7d94d8);
    this.hemi.intensity = up ? 0.28 + elev * 0.3 + (grey ? 0.12 : 0) : 0.16; this.hemi.color.set(up ? 0xbfd6ff : 0x4a5a90);
    if (this.tint) { this.hemi.color.multiply(this.tint); this.sun.color.multiply(this.tint); }       // a place's palette, lightly
    for (const l of this.lamps) { l.mesh.material.emissiveIntensity = this.dark * 1.8 * l.strength; if (l.light) l.light.intensity = this.dark * 1.6 * l.strength; }
    this.moteMat.color.set(this.dark > 0.5 && season !== "winter" ? 0xd8ff8a : 0xffe6a0); this.moteMat.opacity = this.dark > 0.5 ? 0.9 : 0.4;
    this.motes.visible = !RAIN.includes(weather) && !SNOW.includes(weather);
    this.rain.visible = RAIN.includes(weather); this.snow.visible = SNOW.includes(weather);
    if (this.bloom) this.bloom.strength = 0.12 + this.dark * 0.35;
  }
  _motes() {
    const T = this.THREE, N = 90, g = new T.BufferGeometry(), p = new Float32Array(N * 3), r = Math.random;
    for (let i = 0; i < N; i++) { p[i * 3] = -13 + r() * 26; p[i * 3 + 1] = r() * 5; p[i * 3 + 2] = -7 + r() * 12; }
    g.setAttribute("position", new T.BufferAttribute(p, 3));
    this.moteMat = new T.PointsMaterial({ size: 2, sizeAttenuation: false, color: 0xfff2b0, transparent: true, depthWrite: false });
    this.motes = new T.Points(g, this.moteMat); this.motes.userData.seed = Array.from({ length: N }, () => r()); this.scene.add(this.motes);
  }
  _weather() {
    const T = this.THREE, mk = (n, color, size) => { const g = new T.BufferGeometry(), p = new Float32Array(n * 3); for (let i = 0; i < n; i++) { p[i * 3] = -14 + Math.random() * 28; p[i * 3 + 1] = Math.random() * 12; p[i * 3 + 2] = -10 + Math.random() * 18; } g.setAttribute("position", new T.BufferAttribute(p, 3)); const pts = new T.Points(g, new T.PointsMaterial({ size, sizeAttenuation: false, color, transparent: true, opacity: 0.8, depthWrite: false })); pts.visible = false; this.scene.add(pts); return pts; };
    this.rain = mk(500, 0xa8c4dc, 2); this.snow = mk(260, 0xffffff, 2);
  }
  _post() {
    const T = this.THREE;
    if (!(T.EffectComposer && T.UnrealBloomPass && T.ShaderPass)) return;
    const c = this.composer = new T.EffectComposer(this.renderer); c.setPixelRatio(1); c.setSize(RES[0], RES[1]);
    c.addPass(new T.RenderPass(this.scene, this.camera));
    this.bloom = new T.UnrealBloomPass(new T.Vector2(RES[0], RES[1]), 0.2, 0.35, 0.92); c.addPass(this.bloom);
    c.addPass(new T.ShaderPass({
      uniforms: { tDiffuse: { value: null }, res: { value: new T.Vector2(RES[0], RES[1]) } },
      vertexShader: "varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
      fragmentShader: `uniform sampler2D tDiffuse; uniform vec2 res; varying vec2 vUv;
        void main(){
          float d = max(0.0, max(vUv.y - 0.78, 0.30 - vUv.y)); float r = smoothstep(0.0, 0.22, d) * 2.2;
          vec3 c = vec3(0.0); for (int i = 0; i < 12; i++) { float a = float(i) * 2.39996; float rr = sqrt(float(i) / 12.0) * r; c += texture2D(tDiffuse, vUv + vec2(cos(a), sin(a)) * rr / res).rgb; } c /= 12.0;
          c = c / (1.0 + c * 0.35); c = pow(max(c, 0.0), vec3(1.0 / 2.2)); c = (c - 0.5) * 1.12 + 0.5;
          float l = dot(c, vec3(0.299, 0.587, 0.114)); c = mix(vec3(l), c, 1.15); c *= vec3(1.05, 1.0, 0.9);
          float v = smoothstep(1.0, 0.4, distance(vUv, vec2(0.5, 0.5))); c *= mix(0.7, 1.0, v);
          gl_FragColor = vec4(clamp(c, 0.0, 1.0), 1.0);
        }`
    }));
  }
  _tips() {
    const T = this.THREE, ray = new T.Raycaster(), mouse = new T.Vector2(), el = this.renderer.domElement;
    el.addEventListener("mousemove", (e) => {
      const r = el.getBoundingClientRect(); mouse.set((e.clientX - r.left) / r.width * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(mouse, this.camera); const hit = ray.intersectObjects(this.hits.filter((o) => o.visible), false)[0];
      if (!hit) { this.tip.hidden = true; return; }
      const t = hit.object.userData.tip(); this.tip.replaceChildren(Object.assign(document.createElement("b"), { textContent: t.title }), document.createTextNode(t.text)); this.tip.hidden = false;
      const hr = this.host.getBoundingClientRect();
      this.tip.style.left = Math.min(e.clientX - hr.left + 14, hr.width - this.tip.offsetWidth - 6) + "px"; this.tip.style.top = Math.max(6, e.clientY - hr.top - this.tip.offsetHeight - 10) + "px";
    });
    el.addEventListener("mouseleave", () => { this.tip.hidden = true; });
  }
  _frame() {
    if (!this.visible || document.hidden) return;
    const t = this.reduce ? 0 : this.clock.getElapsedTime();
    if (t - this.last < 1 / 30 && !this.reduce) return;            // 30 frames a second is plenty for pixel art
    this.last = t;
    for (const fn of this.updaters) fn(t);
    const mp = this.motes.geometry.attributes.position, seed = this.motes.userData.seed;
    for (let i = 0; i < seed.length; i++) mp.array[i * 3 + 1] = (seed[i] * 5 + t * 0.12 * (0.5 + seed[i])) % 5;
    mp.needsUpdate = true;
    for (const [pts, speed] of [[this.rain, 9], [this.snow, 0.9]]) {
      if (!pts.visible) continue; const a = pts.geometry.attributes.position;
      for (let i = 0; i < a.count; i++) { a.array[i * 3 + 1] -= speed / 30; if (speed < 2) a.array[i * 3] += Math.sin(t + i) * 0.01; if (a.array[i * 3 + 1] < -2) a.array[i * 3 + 1] = 12; }
      a.needsUpdate = true;
    }
    if (this.composer && this.fx !== false) this.composer.render(); else this.renderer.render(this.scene, this.camera);
  }
  dispose() { this.running = false; this.renderer.dispose(); this.renderer.domElement.remove(); }
}
