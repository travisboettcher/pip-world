// The engine's plain page (docs/DESIGN-engine-audit.md, B5): for a world pack with no page of its own. It reads only what every world has:
// /state and the scene's agent (who, doing what, how it is), the scene renderer, /standing (what modules show the agent), /events.
import { SceneView } from './world/scene.js';

const $ = (id) => document.getElementById(id);
const h = (tag, attrs = {}, ...kids) => { const e = Object.assign(document.createElement(tag), attrs); e.append(...kids.filter((k) => k != null)); return e; };
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}
const when = (ts) => new Date(ts * 1000).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' });

// what happened, in a line each (kinds the engine logs in every world, and a module's own event as it says it reads; anything else is left out)
const byModule = (d) => d.by && (d.read?.public || d.read?.line);
const LINES = {
  tick: (d) => d.text,
  module: (d) => d.text,
  arrived: (d) => d.label && `Arrived at ${d.label}.`,
  happening: (d) => d.title && `${d.title}: ${d.text}`,
  reflection: (d) => d.summary,
  made_work: (d) => d.title && `Made ${d.title}.`,
  creation_made: (d) => d.name && `Made ${d.name}: ${d.description}`,
  inbox: (d) => d.text && `${d.sender}: ${d.text}`,
};

let scene = null, name = 'The agent';
async function refreshScene() {
  scene ??= new SceneView($('scene'), { api });
  const d = await scene.show(null);
  const a = d.agent;
  name = a.name; document.title = a.name; $('name').textContent = a.name;
  $('doing').textContent = `${a.name} is ${a.activity}${a.description ? `: ${a.description}` : ''}${a.mood ? ` (feeling ${a.mood})` : ''}.`;
  $('stats').replaceChildren(...(a.stats || []).map((s) => h('li', {}, `${s.label} ${Math.round(s.value * 100)}%`,
    h('span', { className: 'bar' }, h('i', { style: `width:${Math.round(s.value * 100)}%` })))));
  $('where').textContent = a.here ? `At ${d.place.label}.` : `Showing ${d.place.label}.`;
}

async function refreshStanding() {
  const rows = await api('/standing');
  $('standing').replaceChildren(...(rows.length ? rows.flatMap((s) => [h('h3', {}, s.title),
    h('ul', {}, ...(s.lines.length ? s.lines : ['Nothing to show right now.']).map((l) => h('li', {}, l)))])
    : [h('p', { className: 'hint' }, 'Nothing yet.')]));
}

async function refreshEvents() {
  const rows = (await api('/events?limit=80')).map((e) => ({ e, line: (LINES[e.kind] ?? byModule)(e.data || {}) })).filter((x) => x.line).slice(0, 30);
  $('events').replaceChildren(...(rows.length ? rows.map(({ e, line }) => h('li', {}, line, h('small', {}, when(e.ts))))
    : [h('li', { className: 'hint' }, 'Nothing yet.')]));
}

const refresh = () => Promise.allSettled([refreshScene(), refreshStanding(), refreshEvents()]);

$('say').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const text = $('say-text').value.trim();
  if (!text) return;
  try { await api('/inbox', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text }) }); $('say-text').value = ''; $('said').textContent = `Sent. ${name} will read it soon.`; }
  catch (e) { $('said').textContent = e.message; }
});

(async () => {
  try { $('talk').hidden = (await api('/mode')).public; } catch { /* the page still shows */ }
  await refresh();
  let timer = null;
  const stream = new EventSource('/stream');
  stream.onmessage = () => { clearTimeout(timer); timer = setTimeout(refresh, 1500); };
  setInterval(() => scene?.moment(), 30000);
  setInterval(refresh, 5 * 60000);
})();
