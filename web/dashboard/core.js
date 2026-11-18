// What every panel of the engine's dashboard shares (docs/DESIGN-dashboard.md): making elements, asking the engine (for the agent the
// page is about), remembering small choices, and how to say things about the agent: its name and pronoun come from the world.
// All text from the agent, visitors and the world is inserted as text, never as HTML.

export const $ = (id) => document.getElementById(id);
export function h(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === 'class') n.className = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) n.append(kid);
  return n;
}
export const fmtTime = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
export const fmtDay = (ts) => new Date(ts * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
export const pct = (x) => `${Math.round(Math.max(0, Math.min(1, x)) * 100)}%`;
export const fmtTok = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n));
export const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

// In a world of several agents the page is about one of them (?agent=<key>), and every request says which.
export const agentKey = new URLSearchParams(location.search).get('agent') || '';
export const withAgent = (path) => (agentKey ? `${path}${path.includes('?') ? '&' : '?'}agent=${encodeURIComponent(agentKey)}` : path);
export async function api(path, opts) {
  const r = await fetch(withAgent(path), opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch { /* not JSON */ }
    throw new Error(`${r.status} ${msg}`);
  }
  return r.json();
}
export const post = (path, body) => api(path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body ?? {}) });

// Small choices (a tab, the feed's filters), per agent; nothing that matters if it's lost.
export const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(`${agentKey}:${k}`)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(`${agentKey}:${k}`, JSON.stringify(v)); } catch { /* private mode */ } },
};

const timers = {};
export const debounce = (key, fn, ms = 800) => { clearTimeout(timers[key]); timers[key] = setTimeout(fn, ms); };

// How to speak of the agent: ctx.name, ctx.they / them / their (from the world's pronoun), ctx.home (its home's key).
const FORMS = { it: ['it', 'its'], he: ['him', 'his'], she: ['her', 'her'], they: ['them', 'their'] };
export const ctx = {
  name: 'The agent', they: 'they', them: 'them', their: 'their', home: 'home', key: '', kinds: [], public: false, config: {}, state: null,
  agents: [],
  who(identity) {
    const [them, their] = FORMS[identity.they] || [identity.they, `${identity.they}'s`];
    Object.assign(this, { name: identity.name, they: identity.they, them, their, home: identity.home, key: identity.key });
  },
};

// A line from a template the pack gives, with an item's attributes: "keeps {days} days, worth {value}" ({x|0.3}: a default). A
// template naming something the item hasn't, with no default, says nothing.
export function fill(template, attrs) {
  let missing = false;
  const out = template.replace(/\{(\w+)(?:\|([^}]*))?\}/g, (_, k, dflt) => {
    if (attrs[k] != null) return String(attrs[k]);
    if (dflt != null) return dflt;
    missing = true;
    return '';
  });
  return missing ? '' : out;
}

export function bar(label, value, cls = '') {
  return h('div', { class: 'stat' }, h('span', {}, h('span', {}, label), h('b', {}, pct(value))), h('div', { class: `bar ${cls}` }, h('i', { style: `width:${pct(value)}` })));
}
export function section(title, items) { return items.length ? [h('h3', {}, title), h('ul', { class: 'plain' }, ...items)] : []; }
