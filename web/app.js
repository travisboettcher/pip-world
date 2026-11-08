// Pip's web UI: the browser counterpart of `pipchat`. No build step, no dependencies.
// All text from Pip and visitors is inserted with textContent / text nodes, never as HTML.

const $ = (id) => document.getElementById(id);
const SECTIONS = ['diary', 'todo', 'wishlist', 'ambitions', 'learned'];
const GROUPS = [['chat', 'Chat'], ['actions', 'Actions'], ['journal', 'Journal'], ['world', 'World'], ['system', 'System']];
// USD per million tokens (input, output) for the cost estimate; same table as pipchat.
const PRICES = { 'claude-haiku-5-5': [0.10, 0.50] };
const TYPING_TIMEOUT_MS = 150_000;
const SILENT_AFTER_READ_MS = 8_000;

// ---- helpers ----------------------------------------------------------------
function h(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === 'class') n.className = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) n.append(kid);
  return n;
}
const fmtTime = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
const fmtDay = (ts) => new Date(ts * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const pct = (x) => `${Math.round(Math.max(0, Math.min(1, x)) * 100)}%`;
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
};
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch { /* not JSON */ }
    throw new Error(`${r.status} ${msg}`);
  }
  return r.json();
}
const post = (path, body) => api(path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body ?? {}) });
let PUBLIC = false; // set at boot from /mode: the public, read-only view hides every control and the owner-only panels
const timers = {};
const debounce = (key, fn, ms = 800) => { clearTimeout(timers[key]); timers[key] = setTimeout(fn, ms); };

// ---- describing events (mirrors pipchat's format_event) ---------------------
function describeTool(d) {
  const a = d.args || {}, r = String(d.result ?? '');
  if (PUBLIC) return d.result ? { group: 'actions', text: `Pip: ${r}` } : null; // the public feed carries results, not arguments
  if (d.noop) return null; // nothing changed (e.g. restating the same activity)
  switch (d.tool) {
    case 'say': return null; // shown via the 'say' event
    case 'set_activity': return { group: 'actions', text: `Pip is now ${a.activity}` + (a.description ? ` — ${a.description}` : '') };
    case 'note_to_self': {
      const sec = a.section || 'diary';
      if (r.startsWith('not written')) return { group: 'system', cls: 'warn', text: `Pip's ${sec} note was refused: ${r.replace('not written: ', '')}` };
      return { group: 'journal', text: `Pip writes in its ${sec}: ${a.text}` };
    }
    case 'edit_note':
      if (r.startsWith('error') || r.startsWith('not edited')) return { group: 'system', cls: 'warn', text: `Pip couldn't edit #${a.id}: ${r}` };
      return { group: 'journal', text: `Pip rewrites #${a.id}: ${a.text}` };
    case 'resolve_note': return { group: 'journal', text: `Pip crosses off #${a.id}` + (a.outcome ? `: ${a.outcome}` : '') };
    case 'use_item': return { group: 'world', cls: 'world', text: `Pip uses ${a.item}` + (a.purpose ? ` — ${a.purpose}` : '') };
    case 'plant': return { group: 'world', cls: 'world', text: r.startsWith('error') ? `Pip couldn't plant: ${r}` : `Pip: ${r}` };
    case 'harvest': return { group: 'world', cls: 'world', text: `Pip: ${r}` };
    case 'sleep': return { group: 'actions', text: r.startsWith('you go to bed') ? 'Pip goes to bed' : `Pip can't sleep yet: ${r}` };
    case 'gather': return { group: 'actions', text: r.startsWith('you set about') ? `Pip ${r.replace(/^you /, '')}`.replace(/ You'll see.*$/, '') : `Pip can't gather: ${r}` };
    case 'undo_decision': return { group: 'journal', text: `Pip takes back a night decision: ${r}` };
    case 'settle': return null; // shown via the 'settled' event
    case 'eat': return { group: 'actions', text: a.item ? `Pip eats ${a.item}` : 'Pip has a meal' };
    case 'rest': return { group: 'actions', text: 'Pip rests' };
    case 'web_search': return { group: 'actions', text: `Pip searches the web for: ${a.query}` };
    case 'start_project': return { group: 'world', cls: 'world', text: `Pip starts a project: ${a.name}` + (a.goal ? ` — ${a.goal}` : '') };
    case 'work_on': return /^(error|can't|you're in the middle)/.test(r)
      ? { group: 'system', cls: 'warn', text: `Pip can't work yet: ${r}` }
      : { group: 'actions', text: `Pip settles in to work on ${a.project}` + (a.minutes ? ` for ${a.minutes} min` : '') };
    case 'abandon_project': return { group: 'world', cls: 'world', text: `Pip gives up on ${a.project}` + (a.reason ? `: ${a.reason}` : '') };
    case 'tend': return { group: 'world', cls: 'world', text: `Pip ${r}` };
    default: return { group: 'actions', text: `Pip uses ${d.tool}` };
  }
}
function describe(e) {
  const d = e.data;
  switch (e.kind) {
    case 'say': return d.to_name ? { group: 'world', cls: 'world', text: `Pip to ${d.to_name}: ${d.text}` }
      : { group: 'chat', text: `Pip: ${d.text || '(says nothing)'}` };
    case 'work': {
      const tail = d.project_done ? ' — finished!' : d.finished_stage ? ' (stage done)' : ` (${d.percent}%)`;
      if (d.interrupted) return { group: 'actions', text: `Pip stopped working on ${d.project} early${tail}` };
      const cls = ['setback', 'blowup'].includes(d.result) ? 'warn' : 'world';
      return { group: 'world', cls, text: `${d.project}, ${d.stage}: ${d.result} — ${d.text}${tail}` + (d.expectation ? ` (${d.expectation})` : '') + (d.learned ? ` Learned: ${d.learned}` : '') };
    }
    case 'experiment': {
      if (d.interrupted) return { group: 'actions', text: `Pip cut an experiment on ${d.project} short` };
      return { group: 'world', cls: 'world', text: `Experiment on ${d.project} (${d.hypothesis}): ${d.text}` + (d.finding ? ` Learned: ${d.finding}` : '') + (d.expectation ? ` (${d.expectation})` : '') };
    }
    case 'gathered': return { group: 'world', cls: 'world', text: d.text + (d.interrupted ? ' (cut short)' : '') };
    case 'woke': return { group: 'world', cls: 'world', text: `Pip wakes after about ${d.hours} hours of sleep` + (d.early ? ' (woken early)' : '') };
    case 'made_work': return { group: 'world', cls: 'world', text: d.what === 'drawing' ? `Pip drew “${d.title}”${d.caption ? ` — ${d.caption}` : ''}` : `Pip wrote “${d.title}”` };
    case 'world_changed': return { group: 'world', cls: 'world', text: d.text };
    case 'night_pass': {
      const bits = [...(d.decisions || []), ...(d.focus || []).map((f) => `focus: ${f}`)];
      if (!bits.length) return d.failed ? { group: 'system', cls: 'warn', text: 'The night pass failed' } : null;
      return { group: 'journal', text: `Pip's sleeping self${d.mode === 'log' ? ' (logged only)' : ''}: ${bits.join('; ')}` };
    }
    case 'night_undo': return { group: 'journal', text: `Night decision #${d.decision} taken back: ${d.summary}` };
    case 'plan_revised': {
      const bits = [...(d.added || []).map((x) => `+${x}`), ...(d.dropped || []).map((x) => `−${x}`)];
      return bits.length ? { group: 'world', cls: 'world', text: `Pip changed the plan for ${d.project}: ${bits.join(', ')}` } : null;
    }
    case 'creation_made': return { group: 'world', cls: 'world', text: `Pip made ${d.name} (${[d.quality, ...(d.capabilities || [])].join(', ')}): ${d.description}` };
    case 'creation': return { group: 'world', cls: d.what === 'stopped' ? 'warn' : 'world', text: ['stopped', 'helper', 'used'].includes(d.what) ? d.text : `${d.name}: ${d.text}` };
    case 'companion': return { group: 'world', cls: 'world', text: `${d.name}: “${d.text}”` };
    case 'talk': return { group: 'world', cls: 'world', text: `Pip and ${d.name} talked (${d.turns} of Pip's lines; ${d.ended === 'pip' ? 'Pip said goodbye' : d.ended === d.name ? `${d.name} said goodbye` : d.ended})` };
    case 'reflection': return { group: 'journal', text: `Pip slept on it: ${d.summary}` };
    case 'reflection_error': return { group: 'system', cls: 'warn', text: "Pip's nightly reflection failed; it'll retry in an hour" };
    case 'inbox': return d.letter ? { group: 'world', cls: 'world', text: d.text }
      : d.gift ? null : { group: 'chat', text: `${d.sender || 'Visitor'}${d.source && d.source !== 'web' ? ` (via ${d.source})` : ''}: ${d.text}` };
    case 'outreach': {
      const to = d.what === 'postcard' ? 'sent a postcard' : 'answered';
      if (!d.delivered) return { group: 'system', cls: 'warn', text: `Pip tried to send a ${d.what === 'postcard' ? 'postcard' : 'reply'} via ${d.channel} but it didn't go: ${d.error || d.status}` };
      return { group: 'world', cls: 'world', text: `Pip ${to} via ${d.channel}${d.mode === 'log' ? ' (logged only)' : ''}: ${d.text}` };
    }
    case 'arrived': return { group: 'world', cls: 'world', text: d.place === 'workshop' ? 'Pip gets home' : `Pip arrives at ${d.label || d.place}` + (d.first_time && d.description ? ` — ${d.description}` : '') };
    case 'reading': return { group: 'world', cls: 'world', text: `Pip reads ${d.title}${d.finished ? ' (finished!)' : ` (${d.percent}%)`}: ${d.summary}` };
    case 'letter_sent': return { group: 'world', cls: 'world', text: `Pip wrote to ${d.to}: ${d.text}` + (d.enclosed ? ` (enclosed: ${d.enclosed})` : '') };
    case 'neighbor': return { group: 'world', cls: 'world', text: `A neighbor: ${d.name} — ${d.about}` };
    case 'gift': return { group: 'world', cls: 'world', text: `${d.sender} gave Pip ${d.qty} × ${d.item}` };
    case 'garden': return { group: 'world', cls: 'world', text: `Pip's ${d.crop} in plot ${d.plot} are ripe` };
    case 'stall_sale': return { group: 'world', cls: 'world', text: `Pip sold ${d.qty} ${d.item} at its stall for ${d.coins} coin${d.coins === 1 ? '' : 's'}${d.left ? ` (${d.left} left)` : ' (sold out)'}` };
    case 'happening': return { group: 'world', cls: d.tone === 'bad' ? 'warn' : 'world', text: `Something happened — ${d.title}: ${d.text}${d.effects ? ` ${d.effects}` : ''}` };
    case 'reminded': return d.shown && d.shown.length ? { group: 'journal', text: `On Pip's mind: ${d.shown.map((m) => m.text).join(' · ')}` } : null;
    case 'faded': return { group: 'journal', text: `${d.count} old memor${d.count === 1 ? 'y' : 'ies'} faded (recall can still find ${d.count === 1 ? 'it' : 'them'})` };
    case 'wished': return { group: 'journal', text: `Pip wishes (${d.wish}): ${d.text}` };
    case 'happening_felt': return { group: 'journal', text: `Pip took “${d.title}” as ${d.read_as}${d.read_as === d.lens ? '' : ` (it was written as ${d.lens})`}` };
    case 'emotion': return { group: 'world', cls: 'world', text: `Pip's ${d.emotion} is high (${d.value}): ${d.cause}` };
    case 'settled': return { group: 'actions', text: `Pip settles its ${d.emotion} (${d.from} → ${d.to})` + (d.how ? `: ${d.how}` : '') };
    case 'alert': return { group: 'world', cls: 'warn', text: `Pip's ${d.stat} needs attention` };
    case 'budget_exceeded': return { group: 'world', cls: 'bad', text: "Pip has used today's token budget and is asleep until tomorrow." };
    case 'error': return { group: 'system', cls: 'bad', text: String(d.error) };
    case 'tool_error': return { group: 'system', cls: 'warn', text: `tool ${d.tool} failed: ${d.error}` };
    case 'tick': return { group: 'system', cls: 'system', text: `tick (${d.reason}, step ${d.step ?? 0}, ${d.tokens} tokens)` + (d.text ? `: ${d.text}` : '') };
    case 'inbox_read': return { group: 'system', cls: 'system', text: `Pip read visitor message(s) ${(d.ids || []).join(', ')}` };
    case 'start': return { group: 'system', cls: 'system', text: `started: ${d.model} via ${d.backend}, pacing ${d.pacing}` };
    case 'tool': return describeTool(d);
    default: return null;
  }
}

// ---- activity feed ----------------------------------------------------------
let filters = { chat: true, actions: true, journal: true, world: true, system: false, ...store.get('filters', {}) };
function renderFilters() {
  $('filters').replaceChildren(...GROUPS.filter(([key]) => !(PUBLIC && key === 'chat')).map(([key, label]) => h('button', {
    type: 'button', class: 'chip', 'aria-pressed': String(!!filters[key]),
    onclick: () => { filters[key] = !filters[key]; store.set('filters', filters); renderFilters(); applyFilters(); },
  }, label)));
}
const applyFilters = () => { for (const li of $('feed').children) li.hidden = !filters[li.dataset.group]; };
function feedAdd(e) {
  const m = describe(e);
  if (!m) return;
  const firsts = (e.data?.firsts || []).map((f) => f.label);
  const li = h('li', { 'data-group': m.group, class: m.cls || '' }, h('time', {}, fmtTime(e.ts)),
    h('span', {}, m.text, firsts.length ? h('span', { class: 'first' }, `★ ${firsts.join('; ')}`) : null));
  li.hidden = !filters[m.group];
  $('feed').prepend(li);
  while ($('feed').children.length > 400) $('feed').lastChild.remove();
}

// ---- chat -------------------------------------------------------------------
const chat = { seenInbox: new Set(), pending: new Map(), typing: null, open: false, unread: 0 };
function renderBadge() {
  $('chat-badge').hidden = chat.unread === 0;
  $('chat-badge').textContent = String(chat.unread);
  $('chat-toggle').setAttribute('aria-label', chat.unread ? `Chat (${chat.unread} unread)` : 'Chat');
}
function setChatOpen(on, focus = true) {
  chat.open = on;
  $('chat-panel').hidden = !on;
  $('chat-toggle').setAttribute('aria-expanded', String(on));
  store.set('chatOpen', on);
  if (on) {
    chat.unread = 0;
    renderBadge();
    $('chat').scrollTop = $('chat').scrollHeight;
    if (focus) $('chat-input').focus();
  }
}
$('chat-toggle').addEventListener('click', () => setChatOpen(!chat.open));
$('chat-close').addEventListener('click', () => { setChatOpen(false); $('chat-toggle').focus(); });
function bubble(cls, text, ts, via) {
  const box = $('chat');
  const stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
  const node = h('div', { class: `msg ${cls}` }, text, cls === 'sys' || !ts ? null : h('time', {}, fmtTime(ts) + (via && via !== 'web' ? ` · via ${via}` : '')));
  if (chat.typing) box.insertBefore(node, chat.typing); else box.append(node);
  if (stick) box.scrollTop = box.scrollHeight;
  return node;
}
function syncTyping() {
  if (chat.pending.size && !chat.typing) {
    chat.typing = h('div', { class: 'msg pip typing', 'aria-label': 'Pip is thinking' }, 'Pip is thinking');
    $('chat').append(chat.typing);
    $('chat').scrollTop = $('chat').scrollHeight;
  } else if (!chat.pending.size && chat.typing) {
    chat.typing.remove();
    chat.typing = null;
  }
}
function settle(id) {
  const p = chat.pending.get(id);
  if (p) { clearTimeout(p.timer); chat.pending.delete(id); }
}
function trackPending(id) {
  const timer = setTimeout(() => {
    if (!chat.pending.has(id)) return;
    chat.pending.delete(id);
    bubble('sys', 'No answer yet — Pip may be busy or paused. Your message is still queued.');
    syncTyping();
  }, TYPING_TIMEOUT_MS);
  chat.pending.set(id, { timer });
  syncTyping();
}
function showVisitor(id, text, ts, via) {
  if (chat.seenInbox.has(id)) return false;
  chat.seenInbox.add(id);
  bubble('you', text, ts, via);
  return true;
}
function chatFromEvent(e, live) {
  const d = e.data;
  if (e.kind === 'inbox' && !d.gift && !d.letter) {
    if (showVisitor(d.id, d.text, e.ts, d.source) && live && d.source && d.source !== 'web' && !chat.open) { chat.unread += 1; renderBadge(); }
  }
  else if (e.kind === 'gift') bubble('sys', `${d.sender} gave Pip ${d.qty} × ${d.item}`);
  else if (e.kind === 'say' && !d.to_name) {
    if (d.text) {
      bubble('pip', d.text, e.ts);
      if (live && !chat.open) { chat.unread += 1; renderBadge(); }
    } else if (live) bubble('sys', 'Pip says nothing.');
    for (const id of d.to || []) settle(id);
    syncTyping();
  } else if (e.kind === 'inbox_read' && live) {
    for (const id of d.ids || []) {
      const p = chat.pending.get(id);
      if (!p) continue;
      clearTimeout(p.timer);
      p.timer = setTimeout(() => {
        if (!chat.pending.delete(id)) return;
        bubble('sys', 'Pip read your message but chose not to say anything.');
        syncTyping();
      }, SILENT_AFTER_READ_MS);
    }
  }
}
$('chat-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const text = $('chat-input').value.trim();
  if (!text) return;
  $('chat-input').value = '';
  try {
    const r = await post('/inbox', { text, sender: store.get('giver', 'visitor') });
    showVisitor(r.id, text, Date.now() / 1000);
    trackPending(r.id);
  } catch (err) {
    bubble('sys', `Couldn't send: ${err.message}`);
  }
});

// ---- map ----------------------------------------------------------------------
// Pip's world drawn from /map: home in the middle, every place Pip knows of at its fixed spot, and Pip where it is (moving along its walk).
const SVGNS = 'http://www.w3.org/2000/svg';
function sv(tag, attrs = {}, ...kids) {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  for (const kid of kids.flat()) if (kid != null) n.append(kid);
  return n;
}
const MAP_MIN_HALF = 20, MAP_SOFT = 10, MAP_RINGS = [10, 20, 30, 50]; // viewBox units; places nearer than MAP_SOFT minutes keep their distance, farther ones are drawn closer in
let mapData = null;
function mapWhere(m) {
  const w = m.pip.walking, name = (key) => m.places.find((p) => p.key === key)?.label ?? key;
  if (w) return `Pip is walking from ${name(w.from)} to ${name(w.to)} (${Math.round(w.progress * 100)}%).`;
  return m.pip.at === m.home ? 'Pip is home.' : `Pip is at ${name(m.pip.at)}.`;
}
// Far places are drawn closer in than they are (a square root beyond MAP_SOFT) so a distant market doesn't squeeze everything else into the middle.
// The direction from home is kept, and rings mark the real minutes (10, 20, 30...) at the same squashed distance.
const squash = (r) => (r <= MAP_SOFT ? r : MAP_SOFT * Math.sqrt(r / MAP_SOFT));
const TRADE_KINDS = ['shop', 'market'];
function mapLayout(m, width) {
  const home = m.places.find((p) => p.key === m.home) ?? { x: 0, y: 0 };
  const at = (x, y) => { const dx = x - home.x, dy = y - home.y, r = Math.hypot(dx, dy) || 1; const k = squash(r) / r; return [home.x + dx * k, home.y + dy * k]; };
  const placed = m.places.map((p) => { const [sx, sy] = at(p.x, p.y); return { ...p, sx, sy, dir: p.key === m.home ? 0 : sx - home.x < 0 ? -1 : 1 }; });
  const byKey = Object.fromEntries(placed.map((p) => [p.key, p]));
  const w = m.pip.walking && byKey[m.pip.walking.from] && byKey[m.pip.walking.to] ? m.pip.walking : null;
  const pip = w ? { x: byKey[w.from].sx + (byKey[w.to].sx - byKey[w.from].sx) * w.progress, y: byKey[w.from].sy + (byKey[w.to].sy - byKey[w.from].sy) * w.progress }
    : (() => { const [x, y] = at(m.pip.x, m.pip.y); return { x, y }; })();
  let half = 28, u = 0.1;
  for (let i = 0; i < 3; i++) { // label size depends on the scale and the scale on the label size: settle it
    u = (2 * half) / Math.max(280, width);   // viewBox units per CSS pixel
    const char = 6.6 * u;                     // a 12px label's average character
    const reach = placed.map((p) => Math.abs(p.sx) + (p.dir ? 8 * u + char * (p.label.length + 2) : 6 * u));
    half = Math.max(MAP_MIN_HALF, ...reach, ...placed.map((p) => Math.abs(p.sy) + 16 * u), Math.abs(pip.y) + 8 * u) + 8 * u;
  }
  const font = 12 * u, rows = {};
  for (const p of placed) { // labels on the same side that would overlap are pushed apart, top to bottom
    p.ly = p.dir ? p.sy : p.sy + 20 * u; p.lx = p.dir ? p.sx + p.dir * 8 * u : p.sx;
    (rows[p.dir] ??= []).push(p);
  }
  for (const side of [-1, 1]) {
    const col = (rows[side] ?? []).sort((a, b) => a.ly - b.ly);
    for (let i = 1; i < col.length; i++) if (col[i].ly - col[i - 1].ly < font * 1.25) col[i].ly = col[i - 1].ly + font * 1.25;
  }
  return { placed, byKey, home, pip, half, u, font, walking: w };
}
function renderMap() {
  if (!mapData) return;
  const m = mapData, L = mapLayout(m, $('map').clientWidth || 360), { u } = L;
  const rings = MAP_RINGS.filter((min) => squash(min) < L.half).flatMap((min) => {
    const r = squash(min);
    return [sv('circle', { class: 'map-ring', cx: L.home.x, cy: L.home.y, r, 'stroke-width': u }),
            sv('text', { class: 'map-ring-label', x: L.home.x, y: L.home.y - r - 3 * u, 'text-anchor': 'middle', 'font-size': 10 * u }, `${min} min`)];
  });
  const spokes = L.placed.filter((p) => p.key !== m.home).map((p) => sv('line', { class: 'map-path' + (p.visited ? '' : ' unseen'), x1: L.home.x, y1: L.home.y, x2: p.sx, y2: p.sy, 'stroke-width': 1.2 * u, 'stroke-dasharray': `${4 * u} ${4 * u}` }));
  const trail = L.walking ? [sv('line', { class: 'map-walk', x1: L.byKey[L.walking.from].sx, y1: L.byKey[L.walking.from].sy, x2: L.byKey[L.walking.to].sx, y2: L.byKey[L.walking.to].sy, 'stroke-width': 2.4 * u })] : [];
  const r = 5.5 * u;
  const marks = L.placed.map((p) => {
    const faint = p.key !== m.home && !p.visited;
    const x = p.sx, y = p.sy;
    const shape = p.kind === 'home' ? sv('path', { d: `M${x - r * 1.3} ${y + r} V${y - r * 0.2} L${x} ${y - r * 1.5} L${x + r * 1.3} ${y - r * 0.2} V${y + r} Z` })
      : TRADE_KINDS.includes(p.kind) ? sv('rect', { x: x - r * 0.9, y: y - r * 0.9, width: r * 1.8, height: r * 1.8 })
      : sv('circle', { cx: x, cy: y, r });
    const text = sv('text', { x: p.lx, y: p.ly, dy: '.35em', 'text-anchor': p.dir < 0 ? 'end' : p.dir > 0 ? 'start' : 'middle', 'font-size': L.font, 'stroke-width': 3 * u });
    text.textContent = p.label + (p.heard_only ? ' ?' : '');
    const where = p.key === m.home ? 'home' : `${Math.round(p.distance_minutes ?? 0)} min walk${p.visited ? '' : p.heard_only ? ', only heard of' : ', not visited yet'}`;
    return sv('g', { class: `map-place kind-${p.kind}${faint ? ' unseen' : ''}${p.heard_only ? ' heard' : ''}`, 'data-key': p.key, 'stroke-width': 1.2 * u, 'font-size': L.font }, sv('title', {}, `${p.label}: ${where}`), shape, text);
  });
  const pip = sv('g', { class: 'map-pip', 'stroke-width': 1.2 * u }, sv('title', {}, 'Pip'),
    sv('circle', { class: 'map-pip-halo', cx: L.pip.x, cy: L.pip.y, r: 8 * u, 'stroke-width': 1.6 * u }),
    sv('circle', { class: 'map-pip-ring', cx: L.pip.x, cy: L.pip.y, r: 10 * u, 'stroke-width': 1.6 * u }), sv('circle', { cx: L.pip.x, cy: L.pip.y, r: 4.6 * u }));
  const svg = sv('svg', { viewBox: `${-L.half} ${-L.half} ${L.half * 2} ${L.half * 2}`, role: 'img', 'aria-label': `Map of Pip's world. ${mapWhere(m)}` }, rings, spokes, trail, marks, pip);
  const key = (cls, text) => h('span', { class: `lg ${cls}` }, text);
  const legend = h('p', { class: 'map-legend' }, key('lg-home', 'home'), key('lg-wild', 'woods & yards'), key('lg-neighbor', 'neighbors'), key('lg-library', 'library'),
    key('lg-trade', 'shops & markets'), key('lg-pip', 'Pip'), h('span', { class: 'lg-note' }, 'faded: not visited yet · ?: only heard of · rings: minutes\' walk'));
  $('map').replaceChildren(svg, legend);
  $('map-where').textContent = mapWhere(m);
}
window.addEventListener('resize', () => debounce('mapResize', renderMap, 150));
const refreshMap = async () => { mapData = await api('/map'); renderMap(); };

// ---- tabs -------------------------------------------------------------------
const TABS = ['now', 'journal', 'world', 'work', 'mind'];
function showTab(name, remember = true) {
  if (!TABS.includes(name)) name = 'now';
  for (const t of TABS) {
    $(`tab-${t}`).hidden = t !== name;
    $(`tab-btn-${t}`).setAttribute('aria-selected', String(t === name));
    $(`tab-btn-${t}`).tabIndex = t === name ? 0 : -1;
  }
  if (remember) { store.set('tab', name); history.replaceState(null, '', `#${name}`); }
  if (name === 'world') refreshMap().catch(() => {});
}
$('tabbar').addEventListener('click', (ev) => { const b = ev.target.closest('button[data-tab]'); if (b) showTab(b.dataset.tab); });
$('tabbar').addEventListener('keydown', (ev) => {
  if (!['ArrowLeft', 'ArrowRight'].includes(ev.key)) return;
  const i = TABS.findIndex((t) => $(`tab-btn-${t}`).getAttribute('aria-selected') === 'true');
  const next = TABS[(i + (ev.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length];
  showTab(next);
  $(`tab-btn-${next}`).focus();
});
window.addEventListener('hashchange', () => showTab(location.hash.slice(1), false));

// ---- state panels -----------------------------------------------------------
let state = null, notes = {}, noteTab = store.get('noteTab', 'diary'), gardenData = [];
function bar(label, value, cls = '') {
  return h('div', { class: 'stat' }, h('span', {}, label, pct(value)), h('div', { class: `bar ${cls}` }, h('i', { style: `width:${pct(value)}` })));
}
const fmtTok = (n) => n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n);
function meter(label, value, cls = '') {
  return h('div', { class: 'meter', title: `${label} ${pct(value)}` }, h('span', {}, `${label} ${pct(value)}`),
    h('div', { class: `bar ${cls}` }, h('i', { style: `width:${pct(value)}` })));
}
function renderState() {
  if (!state) return;
  const a = state.agent, u = state.usage;
  $('now').replaceChildren(h('b', {}, a.activity), a.description ? ` — ${a.description}` : '');
  const coins = state.coins == null ? null : h('div', { class: 'meter coins', title: `${state.coins} coins` }, h('span', {}, 'Coins'), h('b', {}, String(state.coins)));
  $('meters').replaceChildren(...[meter('Hunger', a.hunger, 'hunger'), meter('Energy', a.energy), coins].filter(Boolean));
  if (PUBLIC) { $('meta').replaceChildren(...[['Mood', a.mood], ['Location', a.location], ['Coins', state.coins], ['Ticks since start', state.ticks]].flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, String(v))])); return; }
  const meta = [['Mood', a.mood], ['Location', a.location], ['Coins', state.coins], ['Model', `${state.model} via ${state.backend}`],
                ['Pacing', state.pacing], ['Ticks since start', state.ticks], ['Inbox waiting', state.pending_inbox],
                ['Tools', state.tools.join(', ')]];
  $('meta').replaceChildren(...meta.flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, String(v))]));

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
$('usage-pill').addEventListener('click', () => {
  const pop = $('usage-pop'), on = pop.hidden;
  pop.hidden = !on;
  $('usage-pill').setAttribute('aria-expanded', String(on));
});
document.addEventListener('click', (ev) => {
  if (!ev.target.closest('.usage-wrap') && !$('usage-pop').hidden) { $('usage-pop').hidden = true; $('usage-pill').setAttribute('aria-expanded', 'false'); }
});
document.addEventListener('keydown', (ev) => {
  if (ev.key !== 'Escape') return;
  if (!$('usage-pop').hidden) { $('usage-pop').hidden = true; $('usage-pill').setAttribute('aria-expanded', 'false'); }
  else if (chat.open) setChatOpen(false);
});
const refreshState = async () => { state = await api('/state'); renderState(); };

// ---- emotion state (the engine's numbers; see DESIGN-emotions.md) ----------------
let emotionData = null;
function renderEmotions() {
  const d = emotionData, card = $('emotions-card');
  if (!d || d.mode === 'off') { card.hidden = true; return; }
  card.hidden = false;
  $('emotions').replaceChildren(...d.emotions.map((e) => h('div', { class: 'emo', title: `${e.name} ${e.value} (usual ${e.baseline})` },
    h('span', { class: 'emo-name' }, e.name), h('div', { class: 'bar' }, h('i', { style: `width:${e.value}%` }), h('u', { style: `left:${e.baseline}%` })),
    h('span', { class: 'emo-val' }, String(e.value)))));
  $('emotions-overall').textContent = `Overall: ${d.valence_word}, ${d.arousal_word}` + (d.blend ? `; it feels like ${d.blend}` : '')
    + (d.mode === 'quiet' ? ' (Pip is not shown this)' : '') + '.';
}
const refreshEmotions = async () => { emotionData = await api('/emotions?limit=1'); renderEmotions(); };

function renderNotes() {
  const status = $('note-status').value;
  $('tabs').replaceChildren(...SECTIONS.map((s) => h('button', {
    type: 'button', role: 'tab', 'aria-selected': String(s === noteTab),
    onclick: () => { noteTab = s; store.set('noteTab', s); renderNotes(); },
  }, `${s} (${(notes[s] || []).filter((m) => !status || status === 'archived' || m.status === status).length})`)));
  const items = (notes[noteTab] || []).filter((m) => !status || status === 'archived' || m.status === status).reverse();
  $('notes').replaceChildren(...(items.length ? items.map((m) => h('li', {},
    h('div', { class: m.status === 'done' ? 'done' : '' }, `#${m.id} ${m.text}`, m.kind && m.kind !== 'thing' ? h('span', { class: 'tag' }, m.kind) : null),
    h('small', {}, fmtDay(m.ts) + (m.status === 'done' ? ` · done${m.outcome ? `: ${m.outcome}` : ''}` : m.status === 'archived' ? ' · archived' : '')
      + (m.edited_at ? ` · edited ${fmtDay(m.edited_at)}` : '')),
  )) : [h('li', { class: 'empty' }, 'nothing here')]));
}
async function refreshNotes() {
  const q = $('note-status').value === 'archived' ? '&status=archived' : '';
  notes = await api(`/notes?limit=200${q}`);
  renderNotes();
}
$('note-status').addEventListener('change', refreshNotes);

async function refreshItems() {
  const items = await api('/items');
  $('items').replaceChildren(...(items.length ? items.map((i) => {
    const at = i.attrs || {};
    const extra = i.kind === 'seed' ? `grows ${at.crop}, ~${at.grow_minutes} min, yields ${at.yield}`
      : i.kind === 'food' ? `fills ${at.food_value ?? 0.3}` : '';
    return h('li', {}, `${i.name} ×${i.qty} `, h('small', {}, [i.kind, i.description, extra].filter(Boolean).join(' · ')));
  }) : [h('li', { class: 'empty' }, 'nothing')]));
}
function renderGarden() {
  const now = Date.now() / 1000;
  $('garden').replaceChildren(...gardenData.map((g) => {
    if (g.state === 'empty') return h('div', { class: 'plot' }, h('span', {}, `Plot ${g.plot}`, h('small', {}, 'empty')));
    const total = g.ready_at - g.planted_at;
    const done = g.state === 'ready' ? 1 : (now - g.planted_at) / total;
    const left = Math.max(0, Math.ceil((g.ready_at - now) / 60));
    return h('div', { class: 'plot' },
      h('span', {}, `Plot ${g.plot}: ${g.crop}`, h('small', {}, g.state === 'ready' ? 'ripe!' : `ready in ~${left} min`)),
      h('div', { class: 'bar' }, h('i', { style: `width:${pct(done)}` })));
  }));
}
// ---- lately: the small things that have happened (see DESIGN-happenings.md) ---------------------------------------
function renderLately(rows) {
  $('lately-card').hidden = !rows.length;
  $('lately').replaceChildren(...rows.map((x) => h('li', { class: `lately-item tone-${x.tone}` },
    h('div', { class: 'lately-head' }, h('b', {}, x.title), h('small', {}, `${fmtDay(x.ts)} · ${x.category}${x.severity === 'minor' ? '' : ` · ${x.severity}`}`)),
    h('p', {}, x.text), x.effects_line ? h('p', { class: 'lately-effects' }, x.effects_line) : null,
    h('small', { class: 'lately-read' }, x.status === 'resolved' ? (x.read_as === x.lens ? `Pip took it as ${x.read_as}` : `told as ${x.lens}; Pip took it as ${x.read_as}`) : x.status === 'applied' ? 'Pip has yet to take it in' : ''))));
}
const refreshLately = async () => { try { renderLately(await api('/happenings?limit=6')); } catch { /* an older server has no happenings */ } };
const refreshGarden = async () => { gardenData = await api('/garden'); renderGarden(); };

let projectData = { projects: [], skills: {} };
function renderProjects() {
  const now = Date.now() / 1000;
  const active = projectData.projects.filter((p) => p.status === 'active');
  const done = projectData.projects.filter((p) => p.status !== 'active').slice(-5).reverse();
  const card = (p) => {
    const st = p.current_stage != null ? p.stages[p.current_stage] : null;
    const mats = st && !st.started ? Object.entries(st.materials).map(([n, q]) => `${q} ${n}`).join(', ') : '';
    const last = p.history[p.history.length - 1];
    const sub = [`${p.craft}, difficulty ${p.difficulty}/5`,
                 st ? `stage ${p.current_stage + 1}/${p.stages.length}: ${st.name}` : null,
                 mats ? `needs ${mats}` : null,
                 p.working_until ? `working, ~${Math.max(1, Math.round((p.working_until - now) / 60))} min left` : null];
    return h('div', { class: 'plot' },
      h('span', {}, `#${p.id} ${p.name}`, h('small', {}, `${p.percent}%`)),
      h('div', { class: 'bar' }, h('i', { style: `width:${p.percent}%` })),
      h('small', { class: 'hint' }, sub.filter(Boolean).join(' · ')),
      last ? h('small', { class: 'hint' }, `Last: ${last.result} — ${last.text}`) : null);
  };
  const skills = Object.entries(projectData.skills).map(([c, v]) => `${c} ${v.level}`).join(', ');
  $('projects').replaceChildren(
    ...(active.length ? active.map(card) : [h('p', { class: 'hint' }, 'No projects going.')]),
    skills ? h('p', { class: 'hint' }, `Skills: ${skills}`) : '',
    ...done.map((p) => h('p', { class: 'hint' }, `${p.status === 'done' ? '✓' : '✗'} ${p.name}`)));
}
const refreshProjects = async () => { projectData = await api('/projects'); renderProjects(); };

let memoryData = null;
const STAT_NAMES = { work_sessions: 'work sessions', minutes_worked: 'minutes worked', with_approach: 'with an approach stated',
  setbacks: 'setbacks', blowups: 'blow-ups', breakthroughs: 'breakthroughs', experiments: 'experiments', projects_finished: 'projects finished',
  visitor_messages: 'visitor messages', notes_written: 'journal entries', letters_sent: 'letters sent', hours_slept: 'hours slept',
  tool_errors: 'tool errors', predictions: 'predictions', surprises: 'surprises', focus_kept: 'focus kept', focus_total: 'focus reviewed' };
function section(title, items) { return items.length ? [h('h3', {}, title), h('ul', { class: 'plain' }, ...items)] : []; }
function renderFocus() {
  const open = (memoryData?.focus || []).filter((f) => f.status === 'open');
  $('focus').replaceChildren(...section('Focus (chosen in its sleep)', open.map((f) => h('li', {}, f.text))));
}
function renderMind() {
  const m = memoryData;
  if (!m) return;
  if (!m.last_reflection_ts) {
    for (const id of ['mind-self', 'mind-beliefs', 'mind-people', 'mind-night', 'mind-caps']) $(id).replaceChildren(h('p', { class: 'hint' }, 'Pip reflects each night; nothing yet.'));
    return;
  }
  $('mind-self').replaceChildren(h('p', {}, m.self || ''),
    m.portraits && m.portraits.length > 1 ? h('p', { class: 'hint' }, `${m.portraits.length} versions of this portrait are kept.`) : null,
    ...section('Days that mattered', (m.turning || []).filter((t) => t.grounded).slice(0, 4).map((t) => h('li', {}, t.text, h('small', {}, fmtDay(t.period_end))))));
  const tag = (i) => (i.grounded ? null : h('span', { class: 'tag' }, 'hunch'));
  $('mind-beliefs').replaceChildren(
    ...section('Beliefs', (m.insights || []).filter((i) => i.grounded).slice(0, 8).map((i) => h('li', {}, i.text, h('small', {}, `importance ${i.importance}${i.support && !['legacy', 'none'].includes(i.support) ? ` · ${i.support}` : ''}`)))),
    ...section('Hunches', (m.insights || []).filter((i) => !i.grounded).slice(0, 4).map((i) => h('li', {}, i.text, tag(i)))),
    ...section('How Pip has changed', (m.changes || []).slice(0, 4).map((c) => h('li', {}, c.text, tag(c), h('small', {}, fmtDay(c.period_end))))));
  const ex = (m.expectations || []).filter((x) => x.kind !== 'step');
  $('mind-people').replaceChildren(
    ...section('People', PUBLIC ? [] : (m.people || []).map((p) => h('li', {}, h('b', {}, p.name), ` — ${p.notes}`))),
    ...section('Days', (m.days || []).slice(0, 5).map((d) => h('li', {}, d.text, h('small', {}, fmtDay(d.period_end))))),
    ex.length ? h('p', { class: 'hint' }, `${ex.length} predictions recorded, ${ex.filter((x) => x.surprising).length} surprising.`) : null);
  const decisions = (m.night_decisions || []).slice(0, 6).map((d) => h('li', { class: d.undone ? 'done' : '' }, `#${d.id} ${d.summary}`,
    h('small', {}, [fmtDay(d.ts), d.undone ? 'undone' : d.applied ? 'applied' : 'logged only', d.reason].filter(Boolean).join(' · '))));
  const recent = (m.stats || []).slice(-3).reverse().map((st) => h('li', {}, st.day, h('small', {},
    Object.entries(STAT_NAMES).filter(([k]) => st[k]).map(([k, label]) => `${st[k]} ${label}`).join(', ') || 'a quiet day')));
  $('mind-night').replaceChildren(...section('Decisions', decisions), ...section('Recent days in numbers', recent),
    decisions.length || recent.length ? null : h('p', { class: 'hint' }, 'Nothing decided in its sleep yet.'));
  const caps = m.capabilities;
  $('mind-caps').replaceChildren(...(caps ? Object.entries({ tool: 'Tools', craft: 'Crafts', ability: 'Abilities' }).flatMap(([g, title]) => {
    const top = Object.entries(caps[g] || {}).filter(([, c]) => c.tries >= 3).sort((x, y) => y[1].tries - x[1].tries).slice(0, 8);
    return top.length ? [h('h3', {}, title), h('div', { class: 'caps' }, ...top.map(([n, c]) => h('span', { class: 'chip', title: `${c.good} good, ${c.neutral} slow, ${c.bad} bad of ${c.tries}` }, `${n} ${c.good}/${c.tries}`)))] : [];
  }) : [h('p', { class: 'hint' }, 'Counted each night from what Pip has actually done.')]));
}
async function refreshMemory() {
  memoryData = await api('/memory');
  renderMind();
  renderFocus();
}

async function refreshLetters() {
  const r = await api('/letters?limit=30');
  const now = Date.now() / 1000;
  $('letters').replaceChildren(
    ...r.neighbors.map((n) => h('p', {}, h('b', {}, n.name), ` — ${n.about}`)),
    h('ul', { class: 'plain' }, ...(r.letters.length ? r.letters.slice().reverse().map((l) => {
      const transit = l.delivered_at ? fmtDay(l.ts) : `on its way, arrives in ~${Math.max(1, Math.round((l.deliver_at - now) / 60))} min`;
      const extra = [l.enclosed && `enclosed: ${l.enclosed}`, l.parcel && `parcel: ${l.parcel.qty} × ${l.parcel.name}`].filter(Boolean);
      return h('li', {}, h('b', {}, `${l.sender} → ${l.recipient}`), `: ${l.text}`,
        h('small', {}, [transit, ...extra].join(' · ')));
    }) : [h('li', { class: 'empty' }, 'no letters yet')])));
}

let worksData = [];
function renderGallery() {
  $('gallery').replaceChildren(...(worksData.length ? worksData.map((w) => w.kind === 'drawing'
    ? h('figure', { class: 'work' },
        h('a', { href: `/works/${w.id}.png?width=1200`, target: '_blank', rel: 'noopener' },
          h('img', { src: `/works/${w.id}.svg`, alt: w.title, loading: 'lazy' })),
        h('figcaption', {}, h('b', {}, `#${w.id} ${w.title}`), w.caption ? ` — ${w.caption}` : '', h('small', {}, fmtDay(w.ts))))
    : h('article', { class: 'work' }, h('h3', {}, `#${w.id} ${w.title}`), h('p', { class: 'poem' }, w.body), h('small', {}, fmtDay(w.ts))))
    : [h('p', { class: 'hint' }, 'Nothing drawn or written yet.')]));
}
const refreshWorks = async () => { worksData = await api('/works?limit=60'); renderGallery(); };

async function refreshCreations() {
  const made = await api('/creations');
  $('creations').replaceChildren(...(made.length ? made.map((c) => {
    const caps = c.spec.capabilities;
    const lively = Object.keys(caps).length > 0;  // art and keepsakes have no running state
    const bits = [c.quality, lively ? (c.running ? 'running' : 'stopped') : null,
                  c.clock ? `reads ${c.clock.reads}` : null, c.character ? `talks as ${c.character}` : null,
                  ...Object.keys(caps).filter((k) => !['timekeeper', 'upkeep', 'companion'].includes(k))];
    return h('li', { class: c.running ? '' : 'done' }, h('b', {}, c.name), ` — ${c.description}`,
      h('small', {}, bits.filter(Boolean).join(' · ') + (c.spec.quirks.length ? ` · quirks: ${c.spec.quirks.join('; ')}` : '')));
  }) : [h('li', { class: 'empty' }, 'nothing yet')]));
}

// ---- actions ----------------------------------------------------------------
$('wake').addEventListener('click', async () => {
  const b = $('wake');
  b.disabled = true;
  try { await post('/tick'); b.textContent = 'Poked!'; } catch (err) { b.textContent = 'Failed'; }
  setTimeout(() => { b.textContent = 'Wake Pip'; b.disabled = false; }, 1500);
});
$('g-kind').addEventListener('change', () => { $('g-seed').hidden = $('g-kind').value !== 'seed'; });
$('g-from').value = store.get('giver', 'visitor');
$('give-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const status = $('g-status');
  const attrs = {};
  if ($('g-kind').value === 'seed') {
    if ($('g-minutes').value) attrs.grow_minutes = Number($('g-minutes').value);
    if ($('g-yield').value) attrs.yield = Number($('g-yield').value);
  }
  const body = { name: $('g-name').value.trim(), qty: Number($('g-qty').value) || 1, kind: $('g-kind').value,
                 description: $('g-desc').value.trim(), message: $('g-message').value.trim(),
                 sender: $('g-from').value.trim() || 'A visitor', attrs };
  store.set('giver', body.sender);
  try {
    const r = await post('/items', body);
    chat.seenInbox.add(r.id); // the gift is shown as its own line, not as a visitor message
    trackPending(r.id);
    status.textContent = `Gave ${body.qty} × ${r.item.name}. Watch the chat for Pip's reaction.`;
    for (const id of ['g-name', 'g-desc', 'g-message']) $(id).value = '';
    refreshItems();
  } catch (err) {
    status.textContent = `Couldn't give that: ${err.message}`;
  }
});

// ---- live events ------------------------------------------------------------
let lastEventId = 0;
function setConn(on) {
  $('conn').className = `dot ${on ? 'on' : 'off'}`;
  $('conn').title = on ? 'live' : 'disconnected - retrying';
}
function handleEvent(e, live) {
  if (e.id <= lastEventId) return; // history/SSE overlap and reconnect replays
  lastEventId = e.id;
  feedAdd(e);
  chatFromEvent(e, live);
  if (!live) return;
  const t = e.data?.tool;
  if (e.kind === 'tool' && ['note_to_self', 'edit_note', 'resolve_note'].includes(t)) debounce('notes', refreshNotes);
  if (e.kind === 'gathered' || (e.kind === 'tool' && ['eat', 'use_item', 'plant', 'harvest', 'gather'].includes(t))) { debounce('items', refreshItems); debounce('garden', refreshGarden); }
  if (e.kind === 'gift') debounce('items', refreshItems);
  if (['gift', 'inbox', 'work', 'experiment', 'creation_made', 'garden', 'alert', 'woke', 'outreach', 'settled', 'emotion'].includes(e.kind)) debounce('emotions', refreshEmotions);
  if (e.kind === 'garden') debounce('garden', refreshGarden);
  if (['happening', 'happening_felt'].includes(e.kind)) { debounce('lately', refreshLately); debounce('state', refreshState, 1200); debounce('items', refreshItems); debounce('garden', refreshGarden); }
  if (e.kind === 'arrived' || (e.kind === 'tool' && t === 'go_to')) debounce('map', refreshMap);
  if (['work', 'experiment'].includes(e.kind) || (e.kind === 'tool' && ['revise_plan', 'resume_project', 'start_project', 'work_on', 'abandon_project', 'set_activity', 'rest'].includes(t))) debounce('projects', refreshProjects);
  if (e.kind === 'made_work') debounce('works', refreshWorks);
  if (['reflection', 'night_pass', 'night_undo', 'woke'].includes(e.kind) || (e.kind === 'tool' && t === 'undo_decision')) debounce('memory', refreshMemory);
  if (['letter_sent', 'letter_read', 'neighbor'].includes(e.kind) || (e.kind === 'inbox' && e.data.letter)) debounce('letters', refreshLetters);
  if (['creation_made', 'creation'].includes(e.kind) || (e.kind === 'tool' && t === 'tend')) debounce('creations', refreshCreations);
  if (e.kind === 'creation' && e.data.what === 'helper') { debounce('items', refreshItems); debounce('garden', refreshGarden); }
  if (['tick', 'alert', 'tool'].includes(e.kind)) debounce('state', refreshState, 1200);
}
function connect() {
  const es = new EventSource(`/stream?after_id=${lastEventId}`);
  es.onopen = () => setConn(true);
  es.onerror = () => setConn(false); // EventSource retries by itself
  es.onmessage = (ev) => { try { handleEvent(JSON.parse(ev.data), true); } catch (err) { console.error(err); } };
}

// ---- boot -------------------------------------------------------------------
renderFilters();
(async function boot() {
  try {
    const mode = await api('/mode');
    PUBLIC = mode.public;
    if (mode.version) { // what is running, so a deploy can be checked at a glance
      const tag = /^v?\d+\.\d+/.test(mode.version) ? h('a', { href: `https://github.com/travisboettcher/pip-world/releases/tag/${mode.version}`, rel: 'noopener' }, mode.version) : mode.version;
      $('version').replaceChildren('pip-world ', tag, mode.revision ? ` · ${mode.revision}` : '');
    }
  } catch { /* an older server: the full dashboard */ }
  document.body.classList.toggle('public', PUBLIC);
  if (PUBLIC) $('tabbar').prepend($('tab-btn-world')); // the map first
  showTab(location.hash.slice(1) || (PUBLIC ? 'world' : store.get('tab', 'now')), false);
  setChatOpen(!PUBLIC && store.get('chatOpen', false), false);
  try {
    const history = await api('/events?limit=300'); // newest first
    await Promise.all([refreshState(), refreshEmotions(), refreshNotes(), refreshItems(), refreshGarden(), refreshProjects(), refreshCreations(), refreshMemory(), PUBLIC ? null : refreshLetters(), refreshWorks(), refreshLately()]);
    for (const e of history.reverse()) handleEvent(e, false);
    $('chat').scrollTop = $('chat').scrollHeight;
  } catch (err) {
    setConn(false);
    $('now').textContent = `Can't reach Pip: ${err.message}`;
  }
  connect();
  setInterval(() => Promise.all([refreshState(), refreshEmotions()]).catch(() => {}), 10_000);
  setInterval(() => Promise.all([refreshNotes(), refreshItems(), refreshGarden(), refreshProjects(), refreshCreations(), refreshMemory()]).catch(() => {}), 60_000);
  setInterval(() => { renderGarden(); renderProjects(); }, 30_000);
  setInterval(() => { if (!$('tab-world').hidden) refreshMap().catch(() => {}); }, 5_000); // Pip walks while you watch
})();
