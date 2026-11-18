// The engine's dashboard (docs/DESIGN-dashboard.md): who the agent is comes from /state, the tabs and their panels from the world pack's
// web/dashboard.json (or the engine's own), and live events from /stream refresh whichever panels they concern. No build step.
import { $, agentKey, api, ctx, debounce, fmtTok, h, pct, post, store, withAgent } from './core.js';
import { PANELS, TABS } from './panels.js';
import { chatFromEvent, chatOpen, setChatOpen, setUpChat } from './chat.js';

// USD per million tokens (input, output) for the cost estimate.
const PRICES = { 'claude-haiku-5-5': [0.10, 0.50] };
const hooks = [];                                   // each built panel's way of staying current: {name, card, refresh, when, every, state, on}
let state = null;

async function packConfig() {
  try { const r = await fetch('pack/dashboard.json'); return r.ok ? await r.json() : {}; } catch { return {}; }
}
async function panelFor(name) {
  if (!name.startsWith('pack:')) return PANELS[name];
  try { return (await import(`./pack/panels/${name.slice(5)}.js`)).default; } catch (err) { console.error(name, err); return null; }
}

// ---- the header: who, doing what, the world's stats, usage --------------------------------------------------------------------------
function meter(label, value, cls = '') {
  return h('div', { class: 'meter', title: `${label} ${pct(value)}` }, h('span', {}, `${label} ${pct(value)}`), h('div', { class: `bar ${cls}` }, h('i', { style: `width:${pct(value)}` })));
}
function renderHeader() {
  const a = state.agent, u = state.usage;
  $('now').replaceChildren(h('b', {}, a.activity), a.description ? ` — ${a.description}` : '');
  const coins = state.coins == null ? null : h('div', { class: 'meter coins', title: `${state.coins} coins` }, h('span', {}, 'Coins'), h('b', {}, String(state.coins)));
  $('meters').setAttribute('aria-label', `${ctx.name}'s ${state.stats.map((s) => s.label).join(' and ')}`);
  $('meters').replaceChildren(...state.stats.map((s) => meter(s.label[0].toUpperCase() + s.label.slice(1), s.value, s.good === 'low' ? 'low-good' : '')), coins);
  if (ctx.public) return;
  const price = PRICES[state.model];
  const cost = price ? (u.input_tokens * price[0] + u.output_tokens * price[1]) / 1e6 : null;
  const share = u.budget ? u.total_tokens / u.budget : 0;
  const per = u.total_tokens ? u.input_tokens / u.total_tokens : 0.9;
  const fullDay = price ? (u.budget * (per * price[0] + (1 - per) * price[1])) / 1e6 : null;
  $('usage-text').textContent = `${fmtTok(u.total_tokens)} / ${fmtTok(u.budget)}` + (cost != null ? ` · $${cost.toFixed(2)}` : '');
  $('usage-bar').style.width = pct(share);
  $('usage-pop').replaceChildren(
    h('p', {}, h('b', {}, `${u.total_tokens.toLocaleString()} of ${u.budget.toLocaleString()} tokens today (${pct(share)})`)),
    h('p', {}, `${u.calls} LLM calls: ${u.input_tokens.toLocaleString()} in, ${u.output_tokens.toLocaleString()} out`),
    cost != null ? h('p', {}, `Estimated cost today: $${cost.toFixed(4)}`) : null,
    fullDay != null ? h('p', { class: 'hint' }, `A full budget is about $${fullDay.toFixed(2)}/day (~$${(fullDay * 30).toFixed(0)}/month).`) : null);
}
async function refreshState() {
  state = await api('/state');
  renderHeader();
  for (const k of hooks) if (k.state) try { k.state(state); } catch (err) { console.error(k.name, err); }
}
function setUpHeader() {
  const close = () => { $('usage-pop').hidden = true; $('usage-pill').setAttribute('aria-expanded', 'false'); };
  $('usage-pill').addEventListener('click', () => { const on = $('usage-pop').hidden; $('usage-pop').hidden = !on; $('usage-pill').setAttribute('aria-expanded', String(on)); });
  document.addEventListener('click', (ev) => { if (!ev.target.closest('.usage-wrap') && !$('usage-pop').hidden) close(); });
  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Escape') return;
    if (!$('usage-pop').hidden) close(); else if (chatOpen()) setChatOpen(false);
  });
  const wake = $('wake');
  wake.textContent = `Wake ${ctx.name}`;
  wake.title = `Wake ${ctx.name} for a tick right now`;
  wake.addEventListener('click', async () => {
    wake.disabled = true;
    try { await post('/tick'); wake.textContent = 'Poked!'; } catch { wake.textContent = 'Failed'; }
    setTimeout(() => { wake.textContent = `Wake ${ctx.name}`; wake.disabled = false; }, 1500);
  });
}
function picker() {
  if (ctx.agents.length < 2) return;
  const pick = h('select', { class: 'picker', 'aria-label': 'Whose page' },
    ...ctx.agents.map((a) => h('option', { value: a.key, selected: a.key === (agentKey || ctx.agents[0].key) }, a.name)));
  pick.addEventListener('change', () => { location.search = `?agent=${encodeURIComponent(pick.value)}`; });
  $('name').replaceWith(pick);
}

// ---- tabs and their cards -----------------------------------------------------------------------------------------------------------
let tabKeys = [];
function showTab(key, remember = true) {
  if (!tabKeys.includes(key)) key = tabKeys[0];
  for (const t of tabKeys) {
    $(`tab-${t}`).hidden = t !== key;
    $(`tab-btn-${t}`).setAttribute('aria-selected', String(t === key));
    $(`tab-btn-${t}`).tabIndex = t === key ? 0 : -1;
  }
  if (remember) { store.set('tab', key); history.replaceState(null, '', `${location.search}#${key}`); }
  for (const k of hooks) if (k.shown && !k.card.closest('[hidden]')) k.refresh().catch(() => {});
}
const refreshNamed = (name) => { for (const k of hooks) if (k.name === name) debounce(name, () => k.refresh().catch(() => {}), 300); };
async function buildTabs(config) {
  let tabs = (config.tabs || TABS).filter((t) => !t.several || ctx.agents.length > 1);
  if (ctx.public) tabs = [...tabs.filter((t) => t.key === 'world'), ...tabs.filter((t) => t.key !== 'world')];     // the map first
  for (const t of tabs) {
    const section = h('section', { id: `tab-${t.key}`, class: 'tab', role: 'tabpanel', 'aria-labelledby': `tab-btn-${t.key}`, hidden: true });
    for (const name of t.panels) {
      const panel = await panelFor(name);
      if (!panel || (panel.owner && ctx.public)) continue;
      const card = h('div', { class: `card${panel.wide ? ' wide' : ''}${panel.owner ? ' owner-only' : ''}` }, h('h2', {}, panel.title()));
      section.append(card);
      try { hooks.push({ name, card, ...panel.build(card, refreshNamed) }); } catch (err) { console.error(name, err); card.remove(); }
    }
    if (!section.children.length) continue;
    $('tabs').append(section);
    $('tabbar').append(h('button', { type: 'button', role: 'tab', 'data-tab': t.key, id: `tab-btn-${t.key}` }, t.title));
    tabKeys.push(t.key);
  }
  $('tabbar').addEventListener('click', (ev) => { const b = ev.target.closest('button[data-tab]'); if (b) showTab(b.dataset.tab); });
  $('tabbar').addEventListener('keydown', (ev) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(ev.key)) return;
    const i = tabKeys.findIndex((t) => $(`tab-btn-${t}`).getAttribute('aria-selected') === 'true');
    const next = tabKeys[(i + (ev.key === 'ArrowRight' ? 1 : tabKeys.length - 1)) % tabKeys.length];
    showTab(next);
    $(`tab-btn-${next}`).focus();
  });
  window.addEventListener('hashchange', () => showTab(location.hash.slice(1), false));
}

// ---- live events --------------------------------------------------------------------------------------------------------------------
let lastEventId = 0;
function setConn(on) {
  $('conn').className = `dot ${on ? 'on' : 'off'}`;
  $('conn').title = on ? 'live' : 'disconnected - retrying';
}
function handleEvent(e, live) {
  if (e.id <= lastEventId) return; // history/SSE overlap and reconnect replays
  lastEventId = e.id;
  for (const k of hooks) if (k.on) k.on(e, live);
  chatFromEvent(e, live);
  if (!live) return;
  for (const k of hooks) if (k.refresh && k.when?.(e)) debounce(k.name, () => k.refresh().catch(() => {}));
  if (['tick', 'alert', 'tool', 'happening'].includes(e.kind)) debounce('state', () => refreshState().catch(() => {}), 1200);
}
function connect() {
  const es = new EventSource(withAgent(`/stream?after_id=${lastEventId}`));
  es.onopen = () => setConn(true);
  es.onerror = () => setConn(false); // EventSource retries by itself
  es.onmessage = (ev) => { try { handleEvent(JSON.parse(ev.data), true); } catch (err) { console.error(err); } };
}

// ---- boot ---------------------------------------------------------------------------------------------------------------------------
(async function boot() {
  try {
    const mode = await api('/mode');
    ctx.public = mode.public;
    if (mode.version) { // what is running, so a deploy can be checked at a glance
      const tag = /^v?\d+\.\d+/.test(mode.version) ? h('a', { href: `https://github.com/travisboettcher/pip-world/releases/tag/${mode.version}`, rel: 'noopener' }, mode.version) : mode.version;
      $('version').replaceChildren('pip-world ', tag, mode.revision ? ` · ${mode.revision}` : '');
    }
  } catch { /* the full dashboard */ }
  document.body.classList.toggle('public', ctx.public);
  try {
    state = await api('/state');
  } catch (err) {
    setConn(false);
    $('now').textContent = `Can't reach the world: ${err.message}`;
    return;
  }
  ctx.who(state.identity);
  ctx.kinds = state.item_kinds;
  ctx.state = state;
  try { ctx.agents = (await api('/agents')).agents; } catch { ctx.agents = []; }
  ctx.config = await packConfig();
  if (ctx.config.theme) document.head.append(h('link', { rel: 'stylesheet', href: `pack/${ctx.config.theme}` }));   // the pack's look
  document.title = ctx.name;
  $('name').textContent = ctx.name;
  picker();
  setUpHeader();
  setUpChat();
  await buildTabs(ctx.config);
  showTab(location.hash.slice(1) || (ctx.public ? 'world' : store.get('tab', 'now')), false);
  setChatOpen(!ctx.public && store.get('chatOpen', false), false);
  renderHeader();
  for (const k of hooks) if (k.state) try { k.state(state); } catch (err) { console.error(k.name, err); }
  await Promise.allSettled(hooks.filter((k) => k.refresh).map((k) => k.refresh()));
  try {
    const past = await api('/events?limit=300'); // newest first
    for (const e of past.reverse()) handleEvent(e, false);
    $('chat').scrollTop = $('chat').scrollHeight;
  } catch (err) { setConn(false); }
  connect();
  setInterval(() => refreshState().catch(() => {}), 10_000);
  for (const k of hooks) if (k.refresh && k.every) setInterval(() => k.refresh().catch(() => {}), k.every);
})();
