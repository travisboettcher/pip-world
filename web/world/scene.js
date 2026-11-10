// A place's scene (docs/DESIGN-world-view.md): fetches /world/scene for a place, builds the template for its kind with the kit, and keeps it
// up to date. Kinds without a template yet get a short written description instead, so every place on the map can still be opened.
import { loadThree, Kit } from "./kit.js";
import { makeArt } from "./art.js";
import * as home from "./templates/home.js";
import * as neighbor from "./templates/neighbor.js";
import * as market from "./templates/market.js";
import * as shop from "./templates/shop.js";
import * as library from "./templates/library.js";
import { moduleObjects } from "./templates/parts.js";
import * as layout from "./layout.js";

const TEMPLATES = { home, neighbor, market, shop, library };          // wild places, yards and sights are layouts now (the "outdoors" module)

export class SceneView {
  constructor(host, { api, onShown } = {}) {
    this.host = host; this.api = api; this.onShown = onShown; this.kit = null; this.built = null; this.key = null; this.data = null;
    this.tip = document.createElement("div"); this.tip.className = "scene-tip"; this.tip.hidden = true;
    this.note = document.createElement("div"); this.note.className = "scene-note"; this.note.hidden = true;
    host.append(this.tip, this.note);
  }
  async show(place) {                                   // place: a key, or null for wherever Pip is
    const data = await this.api(`/world/scene${place ? `?place=${encodeURIComponent(place)}` : ""}`);
    const key = data.place.key, tpl = data.layout ? layout : TEMPLATES[data.place.kind];      // a place built from parts, or its hand-written scene
    const sig = JSON.stringify([key, data.place.kind, data.place.scene, data.place.props, data.layout && [data.layout.module, data.layout.version, data.now.season]]);
    if (sig !== this.sig || !this.built) {
      this.clear(); this.key = key; this.sig = sig;
      if (tpl) {
        const THREE = await loadThree();
        this.kit = new Kit(this.host, THREE, this.tip); if (data.place.scene?.palette) this.kit.palette(data.place.scene.palette);
        const art = makeArt(THREE);
        this.built = tpl.build(this.kit, art, data);
        this.objects = moduleObjects(this.kit, art);           // what modules show, on the anchors the server chose
      } else this.built = { update: () => {} };
    }
    this.data = data; this.fetchedAt = Date.now();
    this.built.update(data); this.objects?.update(data.objects || []); this.moment();
    this.note.hidden = !!tpl; if (!tpl) this.note.replaceChildren(...placeholder(data));
    this.onShown?.(data);
    return data;
  }
  refresh() { return this.key ? this.show(this.key) : null; }
  moment() {                                            // the scene's clock runs on from the moment the data was fetched
    if (!this.kit || !this.data) return;
    const n = this.data.now, minutes = Math.floor(n.minutes + (Date.now() - this.fetchedAt) / 60000) % 1440;
    this.kit.setMoment({ minutes, weather: n.weather, season: n.season });
  }
  set effects(on) { if (this.kit) this.kit.fx = on; }
  clear() { this.kit?.dispose(); this.kit = null; this.built = null; this.objects = null; this.key = null; this.sig = null; }
}

function placeholder(d) {
  const p = d.place, el = (t, text) => Object.assign(document.createElement(t), { textContent: text });
  return [el("h3", p.label[0].toUpperCase() + p.label.slice(1)), el("p", p.description || p.blurb || ""),
    el("p", d.present.length ? `Here now: ${d.present.map((c) => c.name).join(", ")}.` : ""),
    el("p", "Its scene is drawn from a layout, and none is ready for it yet.")];
}
