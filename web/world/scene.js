// A place's scene (docs/DESIGN-world-view.md): fetches /world/scene for a place, builds the template for its kind with the kit, and keeps it
// up to date. Kinds without a template yet get a short written description instead, so every place on the map can still be opened.
import { loadThree, Kit } from "./kit.js";
import { makeArt } from "./art.js";
import * as home from "./templates/home.js";

const TEMPLATES = { home };

export class SceneView {
  constructor(host, { api, onShown } = {}) {
    this.host = host; this.api = api; this.onShown = onShown; this.kit = null; this.built = null; this.key = null; this.data = null;
    this.tip = document.createElement("div"); this.tip.className = "scene-tip"; this.tip.hidden = true;
    this.note = document.createElement("div"); this.note.className = "scene-note"; this.note.hidden = true;
    host.append(this.tip, this.note);
  }
  async show(place) {                                   // place: a key, or null for wherever Pip is
    const data = await this.api(`/world/scene${place ? `?place=${encodeURIComponent(place)}` : ""}`);
    const key = data.place.key, tpl = TEMPLATES[data.place.kind];
    if (key !== this.key || !this.built) {
      this.clear(); this.key = key;
      if (tpl) {
        const THREE = await loadThree();
        this.kit = new Kit(this.host, THREE, this.tip); this.built = tpl.build(this.kit, makeArt(THREE), data);
      } else this.built = { update: () => {} };
    }
    this.data = data; this.fetchedAt = Date.now();
    this.built.update(data); this.moment();
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
  clear() { this.kit?.dispose(); this.kit = null; this.built = null; this.key = null; }
}

function placeholder(d) {
  const p = d.place, el = (t, text) => Object.assign(document.createElement(t), { textContent: text });
  return [el("h3", p.label[0].toUpperCase() + p.label.slice(1)), el("p", p.description || p.blurb || ""),
    el("p", d.present.length ? `Here now: ${d.present.map((c) => c.name).join(", ")}.` : ""),
    el("p", "This kind of place doesn't have its drawn scene yet; it's coming in the next step.")];
}
