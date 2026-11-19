// The engine's panels (docs/DESIGN-dashboard.md): each is a card's content. A panel has a `title` (said of the agent), may be `wide` or
// `owner` (never in the public view), and `build(card)` fills the card and returns how it stays current: `refresh()`, `when(e)` (a live
// event that should refresh it), `every` (ms between refreshes) and `state(s)` (called with each new /state).
import { WorldMap } from './world/map.js';
import { SceneView } from './world/scene.js';
import { api, bar, cap, ctx, fill, fmtDay, h, post, section, store, withAgent } from './core.js';
import { seen, trackPending } from './chat.js';
import { feed } from './feed.js';

// Several panels read the same thing (the mind's five read /memory): one request serves them all for a moment.
const recent = new Map();
function read(path, fresh = 1500) {
  const got = recent.get(path);
  if (got && Date.now() - got.at < fresh) return got.p;
  const p = api(path);
  recent.set(path, { at: Date.now(), p });
  p.catch(() => recent.delete(path));
  return p;
}
const tool = (e, ...names) => e.kind === 'tool' && names.includes(e.data?.tool);

// ---- now ----------------------------------------------------------------------------------------------------------------------------
const rightNow = {
  title: () => `${ctx.name} right now`,
  build(card) {
    const meta = h('dl', { class: 'meta' }), focus = h('div');
    card.append(meta, focus);
    const focusNow = async () => {
      const m = await read('/memory');
      focus.replaceChildren(...section(`Focus (chosen in ${ctx.their} sleep)`, (m.focus || []).filter((f) => f.status === 'open').map((f) => h('li', {}, f.text))));
    };
    return {
      state(s) {
        const a = s.agent;
        const rows = ctx.public ? [['Mood', a.mood], ['Location', a.location], ['Coins', s.coins], ['Ticks since start', s.ticks]]
          : [['Mood', a.mood], ['Location', a.location], ['Coins', s.coins], ['Model', `${s.model} via ${s.backend}`], ['Pacing', s.pacing],
             ['Ticks since start', s.ticks], ['Inbox waiting', s.pending_inbox], ['Tools', s.tools.join(', ')]];
        meta.replaceChildren(...rows.filter(([, v]) => v != null).flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, String(v))]));
      },
      refresh: focusNow, every: 60_000, when: (e) => ['night_pass', 'night_undo', 'woke'].includes(e.kind),
    };
  },
};

const lately = {
  title: () => 'Lately',
  build(card) {
    const list = h('ul', { class: 'plain lately' });
    card.append(list, h('p', { class: 'hint' }, `Small things that happen in ${ctx.name}'s world. The line in brackets is what really changed.`));
    return {
      async refresh() {
        const rows = await api('/happenings?limit=6');
        card.hidden = !rows.length;
        list.replaceChildren(...rows.map((x) => h('li', { class: `lately-item tone-${x.tone}` },
          h('div', { class: 'lately-head' }, h('b', {}, x.title), h('small', {}, `${fmtDay(x.ts)} · ${x.category}${x.severity === 'minor' ? '' : ` · ${x.severity}`}`)),
          h('p', {}, x.text), x.effects_line ? h('p', { class: 'lately-effects' }, x.effects_line) : null,
          h('small', { class: 'lately-read' }, x.status === 'resolved' ? (x.read_as === x.lens ? `${ctx.name} took it as ${x.read_as}` : `told as ${x.lens}; ${ctx.name} took it as ${x.read_as}`)
            : x.status === 'applied' ? `${ctx.name} has yet to take it in` : ''))));
      },
      when: (e) => ['happening', 'happening_felt'].includes(e.kind),
    };
  },
};

const emotions = {
  title: () => 'Emotion state',
  build(card) {
    const grid = h('div', { class: 'emotions' }), overall = h('p', { class: 'hint' });
    card.append(grid, overall);
    return {
      async refresh() {
        const d = await api('/emotions?limit=1');
        card.hidden = !d || d.mode === 'off';
        if (card.hidden) return;
        grid.replaceChildren(...d.emotions.map((e) => h('div', { class: 'emo', title: `${e.name} ${e.value} (usual ${e.baseline})` },
          h('span', { class: 'emo-name' }, e.name), h('div', { class: 'bar' }, h('i', { style: `width:${e.value}%` }), h('u', { style: `left:${e.baseline}%` })),
          h('span', { class: 'emo-val' }, String(e.value)))));
        overall.textContent = `Overall: ${d.valence_word}, ${d.arousal_word}` + (d.blend ? `; it feels like ${d.blend}` : '')
          + (d.mode === 'quiet' ? ` (${ctx.name} is not shown this)` : '') + '.';
      },
      every: 10_000,
      when: (e) => ['gift', 'inbox', 'creation_made', 'module', 'alert', 'woke', 'outreach', 'settled', 'emotion'].includes(e.kind) || e.data?.read?.feel,
    };
  },
};

// ---- journal ------------------------------------------------------------------------------------------------------------------------
const SECTIONS = ['diary', 'todo', 'wishlist', 'ambitions', 'learned', 'calendar'];
const journal = {
  title: () => 'Journal', wide: true,
  build(card) {
    let notes = {}, tab = store.get('noteTab', 'diary');
    const tabs = h('div', { class: 'tabs', role: 'tablist', 'aria-label': 'Journal sections' }), list = h('ul', { class: 'notes' });
    const status = h('select', { id: 'note-status' }, ...[['', 'all'], ['open', 'open'], ['done', 'done'], ['archived', 'archived']]
      .map(([v, l]) => h('option', { value: v, selected: v === 'open' }, l)));
    const render = () => {
      const st = status.value, shown = (m) => !st || st === 'archived' || m.status === st;
      tabs.replaceChildren(...SECTIONS.map((s) => h('button', { type: 'button', role: 'tab', 'aria-selected': String(s === tab),
        onclick: () => { tab = s; store.set('noteTab', s); render(); } }, `${s} (${(notes[s] || []).filter(shown).length})`)));
      const items = (notes[tab] || []).filter(shown).reverse();
      list.replaceChildren(...(items.length ? items.map((m) => h('li', {},
        h('div', { class: m.status === 'done' ? 'done' : '' }, `#${m.id} ${m.text}`, m.kind && m.kind !== 'thing' ? h('span', { class: 'tag' }, m.kind) : null,
          m.due_at ? h('span', { class: 'tag' }, `${fmtDay(m.due_at)}${m.place ? ` · ${m.place}` : ''}${m.every ? ' · weekly' : ''}`) : null),
        h('small', {}, fmtDay(m.ts) + (m.status === 'done' ? ` · done${m.outcome ? `: ${m.outcome}` : ''}` : m.status === 'archived' ? ' · archived' : '')
          + (m.edited_at ? ` · edited ${fmtDay(m.edited_at)}` : '')))) : [h('li', { class: 'empty' }, 'nothing here')]));
    };
    const refresh = async () => { notes = await api(`/notes?limit=200${status.value === 'archived' ? '&status=archived' : ''}`); render(); };
    status.addEventListener('change', refresh);
    card.append(h('div', { class: 'row' }, tabs, h('label', { class: 'sr', for: 'note-status' }, 'Status'), status), list);
    return { refresh, every: 60_000, when: (e) => tool(e, 'note_to_self', 'edit_note', 'resolve_note') || e.kind === 'night_pass' };
  },
};

// ---- the world ----------------------------------------------------------------------------------------------------------------------
// The parchment map (web/world/map.js) and a place's scene (web/world/scene.js): the card switches between them.
const map = {
  title: () => 'Map', wide: true,
  build(card) {
    let data = null, worldMap = null, scene = null, mode = 'map';
    const title = card.querySelector('h2');
    const here = h('button', { type: 'button', 'aria-pressed': 'false' }, `Where ${ctx.name} is`), toMap = h('button', { type: 'button', 'aria-pressed': 'true' }, 'Map');
    const find = h('button', { type: 'button' }, `Find ${ctx.name}`), zin = h('button', { type: 'button', 'aria-label': 'Zoom in' }, '+'),
      zout = h('button', { type: 'button', 'aria-label': 'Zoom out' }, '−');
    const tools = h('span', { class: 'wm-tools' }, find, zin, zout);
    const sceneBox = h('div', { class: 'scene', hidden: true }), mapBox = h('div', { class: 'map' });
    const where = h('p', { class: 'hint', role: 'status' });
    const head = h('div', { class: 'map-head' });
    title.before(head);
    head.append(title, h('div', { class: 'wm-tools' }, here, toMap, tools));
    card.append(sceneBox, mapBox, where);
    const label = (key) => data?.places.find((p) => p.key === key)?.label ?? key;
    const mapWhere = () => {
      const w = data.agent.walking;
      if (w) return `${ctx.name} is walking from ${label(w.from)} to ${label(w.to)} (${Math.round(w.progress * 100)}%).`;
      return data.agent.at === data.home ? `${ctx.name} is home.` : `${ctx.name} is at ${label(data.agent.at)}.`;
    };
    const setMode = (m) => {
      mode = m;
      sceneBox.hidden = m !== 'scene'; mapBox.hidden = m !== 'map'; tools.hidden = m !== 'map';
      toMap.setAttribute('aria-pressed', String(m === 'map'));
      if (m === 'map') { title.textContent = 'Map'; here.setAttribute('aria-pressed', 'false'); if (data) where.textContent = mapWhere(); }
    };
    const caption = (d) => {
      const a = d.agent;
      if (a.here) return `${ctx.name} is here: ${(a.description || a.activity).replace(/[.!]+$/, '')}.`;
      if (a.walking) return `${ctx.name} isn't here; ${ctx.they}'s on ${ctx.their} way to ${label(data?.agent.walking?.to)}.`;
      return `${ctx.name} isn't here; ${ctx.they}'s at ${a.where === data?.home ? 'home' : label(a.where)}.` + (d.place.open === false ? ' This place is shut just now.' : '');
    };
    const openScene = async (place) => {
      scene ??= new SceneView(sceneBox, { api });
      setMode('scene');
      try {
        const d = await scene.show(place);
        title.textContent = d.place.kind === 'home' ? `${cap(ctx.name)}'s home` : cap(d.place.label);
        here.setAttribute('aria-pressed', String(d.agent.here));
        where.textContent = caption(d);
      } catch (err) { where.textContent = `Couldn't draw this place: ${err.message}`; }
    };
    toMap.addEventListener('click', () => setMode('map'));
    here.addEventListener('click', () => { if (data?.agent.walking) setMode('map'); else openScene(null); });
    find.addEventListener('click', () => worldMap?.centreOnAgent());
    zin.addEventListener('click', () => worldMap?.zoom(1.5));
    zout.addEventListener('click', () => worldMap?.zoom(1 / 1.5));
    setInterval(() => { if (mode === 'scene' && !card.closest('[hidden]')) scene?.moment(); }, 20_000);
    let first = true;
    return {
      async refresh() {
        if (card.closest('[hidden]')) return;                               // only while its tab shows: the agent walks while you watch
        data = await api('/world/map');
        worldMap ??= new WorldMap(mapBox, { onPlace: (p) => openScene(p.key) });
        worldMap.set(data);
        if (mode === 'map') where.textContent = mapWhere();
        else scene?.refresh().catch(() => {});
        if (first && !data.agent.walking) { first = false; openScene(null); }
      },
      every: 5_000, shown: true, when: (e) => e.kind === 'arrived' || tool(e, 'go_to'),
    };
  },
};

const belongings = {
  title: () => 'Belongings',
  build(card) {
    const list = h('ul', { class: 'plain' });
    card.append(list);
    return {
      async refresh() {
        const items = await api('/items'), lines = ctx.config.items || {};
        list.replaceChildren(...(items.length ? items.map((i) => {
          const extra = lines[i.kind] ? fill(lines[i.kind], i.attrs || {}) : '';
          return h('li', {}, `${i.name} ×${i.qty} `, h('small', {}, [i.kind, i.description, extra].filter(Boolean).join(' · ')));
        }) : [h('li', { class: 'empty' }, 'nothing')]));
      },
      every: 60_000, when: (e) => ['gathered', 'tool', 'gift', 'happening'].includes(e.kind) || (e.kind === 'creation' && e.data.what === 'helper'),
    };
  },
};

// What live modules show the agent every time: each a titled list.
const standing = {
  title: () => 'Going on',
  build(card) {
    const box = h('div');
    card.append(box);
    return {
      async refresh() {
        const rows = await api('/standing');
        card.hidden = !rows.length;
        box.replaceChildren(...rows.map((s) => h('div', { class: 'standing' }, h('h3', {}, s.title),
          h('ul', { class: 'plain' }, ...(s.lines.length ? s.lines : ['Nothing to show right now.']).map((l) => h('li', {}, l))))));
      },
      every: 60_000, when: (e) => ['gathered', 'tool', 'module', 'happening'].includes(e.kind) || e.data?.by,
    };
  },
};

const letters = {
  title: () => 'People & letters', owner: true,
  build(card) {
    const box = h('div');
    card.append(box);
    return {
      async refresh() {
        const [r, people] = await Promise.all([api('/letters?limit=30'), api('/characters')]);
        const now = Date.now() / 1000;
        box.replaceChildren(
          ...section('People', people.map((p) => h('li', {}, h('b', {}, p.name), ` — ${p.about || p.kind}`, p.place ? h('small', {}, p.place) : null))),
          h('h3', {}, 'Letters'),
          h('ul', { class: 'plain' }, ...(r.letters.length ? r.letters.slice().reverse().map((l) => {
            const transit = l.delivered_at ? fmtDay(l.ts) : `on its way, arrives in ~${Math.max(1, Math.round((l.deliver_at - now) / 60))} min`;
            const extra = [l.enclosed && `enclosed: ${l.enclosed}`, l.parcel && `parcel: ${l.parcel.qty} × ${l.parcel.name}`].filter(Boolean);
            return h('li', {}, h('b', {}, `${l.sender} → ${l.recipient}`), `: ${l.text}`, h('small', {}, [transit, ...extra].join(' · ')));
          }) : [h('li', { class: 'empty' }, 'no letters yet')])));
      },
      every: 60_000, when: (e) => ['letter_sent', 'letter_read', 'character'].includes(e.kind) || (e.kind === 'inbox' && e.data.letter),
    };
  },
};

// The owner gives the agent something: the world's item kinds, and any fields the pack asks for one (dashboard.json `give`).
const give = {
  title: () => `Give ${ctx.name} something`, owner: true,
  build(card, refreshAll) {
    const extras = ctx.config.give || {};
    const name = h('input', { required: true, maxlength: 60 }), qty = h('input', { type: 'number', min: 1, max: 999, value: 1 });
    const kind = h('select', {}, ...ctx.kinds.map((k) => h('option', { value: k }, k)));
    const fields = Object.fromEntries(Object.entries(extras).map(([k, fs]) => [k, fs.map((f) => ({ ...f, input: h('input', { type: f.type || 'number', min: 1, placeholder: f.placeholder || '' }) }))]));
    const extraBox = h('div', { class: 'row' });
    const showExtras = () => extraBox.replaceChildren(...(fields[kind.value] || []).map((f) => h('label', {}, `${f.label} `, f.input)));
    kind.addEventListener('change', showExtras);
    showExtras();
    const desc = h('input', { maxlength: 200, placeholder: 'optional' }), message = h('input', { maxlength: 300 }), from = h('input', { maxlength: 40, value: store.get('giver', 'visitor') });
    const status = h('p', { class: 'hint', role: 'status' });
    const form = h('form', { class: 'give' }, h('label', {}, 'Name ', name), h('div', { class: 'row' }, h('label', {}, 'Kind ', kind), h('label', {}, 'Qty ', qty)),
      extraBox, h('label', {}, 'Description ', desc), h('label', {}, 'Say something ', message), h('label', {}, 'From ', from), h('button', { type: 'submit' }, 'Give'), status);
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const attrs = Object.fromEntries((fields[kind.value] || []).filter((f) => f.input.value).map((f) => [f.attr, f.type === 'text' ? f.input.value : Number(f.input.value)]));
      const body = { name: name.value.trim(), qty: Number(qty.value) || 1, kind: kind.value, description: desc.value.trim(), message: message.value.trim(),
                     sender: from.value.trim() || 'A visitor', attrs };
      store.set('giver', body.sender);
      try {
        const r = await post('/items', body);
        seen(r.id);
        trackPending(r.id);
        status.textContent = `Gave ${body.qty} × ${r.item.name}. Watch the chat for ${ctx.name}'s reaction.`;
        for (const i of [name, desc, message]) i.value = '';
        refreshAll?.('belongings');
      } catch (err) { status.textContent = `Couldn't give that: ${err.message}`; }
    });
    card.append(form);
    return {};
  },
};

// ---- work ---------------------------------------------------------------------------------------------------------------------------
// What a module publishes as `projects` and `skills` (the crafting module), read with every other module's at /published.
const projects = {
  title: () => 'Projects',
  build(card) {
    let data = { projects: [], skills: {} }, session = null;
    const box = h('div');
    card.append(box);
    const render = () => {
      const now = Date.now() / 1000;
      const until = (p) => (session && session.kind === 'module' && session.about === p.name ? session.ends_at : null);
      const active = data.projects.filter((p) => p.status === 'active');
      const done = data.projects.filter((p) => p.status !== 'active').slice(-5).reverse();
      const row = (p) => {
        const st = p.current_stage != null ? p.stages[p.current_stage] : null;
        const mats = Object.entries(p.needs || {}).map(([n, q]) => `${q} ${n}`).join(', ');
        const sub = [`${p.craft}, difficulty ${p.difficulty}/5`, st ? `stage ${p.current_stage + 1}/${p.stages.length}: ${st.name}` : null,
          mats ? `needs ${mats}` : null, until(p) ? `working, ~${Math.max(1, Math.round((until(p) - now) / 60))} min left` : null];
        return h('div', { class: 'project' }, h('span', {}, `#${p.id} ${p.name}`, h('small', {}, `${p.percent}%`)),
          h('div', { class: 'bar' }, h('i', { style: `width:${p.percent}%` })), h('small', { class: 'hint' }, sub.filter(Boolean).join(' · ')),
          p.last ? h('small', { class: 'hint' }, `Last: ${p.last.result} — ${p.last.text}`) : null);
      };
      const skills = Object.entries(data.skills).map(([c, v]) => `${c} ${v.level}`).join(', ');
      box.replaceChildren(...(active.length ? active.map(row) : [h('p', { class: 'hint' }, 'No projects going.')]),
        skills ? h('p', { class: 'hint' }, `Skills: ${skills}`) : '', ...done.map((p) => h('p', { class: 'hint' }, `${p.status === 'done' ? '✓' : '✗'} ${p.name}`)));
    };
    setInterval(render, 30_000);
    return {
      async refresh() {
        const said = Object.values(await api('/published')).find((f) => Array.isArray(f.projects));
        card.hidden = !said;
        data = { projects: said?.projects || [], skills: said?.skills || {} };
        render();
      },
      state(s) { session = s.session; render(); },
      every: 60_000, when: (e) => e.data?.by === 'crafting' || (e.kind === 'tool' && (e.data?.module === 'crafting' || ['set_activity', 'rest'].includes(e.data?.tool))),
    };
  },
};

const creations = {
  title: () => `Made by ${ctx.name}`,
  build(card) {
    const list = h('ul', { class: 'plain' });
    card.append(list);
    return {
      async refresh() {
        const made = await api('/creations');
        list.replaceChildren(...(made.length ? made.map((c) => {
          const caps = c.spec.capabilities, lively = Object.keys(caps).length > 0;  // art and keepsakes have no running state
          const bits = [c.quality, lively ? (c.running ? 'running' : 'stopped') : null, c.clock ? `reads ${c.clock.reads}` : null,
            c.character ? `talks as ${c.character}` : null, ...Object.keys(caps).filter((k) => !['timekeeper', 'upkeep', 'companion'].includes(k))];
          return h('li', { class: c.running ? '' : 'done' }, h('b', {}, c.name), ` — ${c.description}`,
            h('small', {}, bits.filter(Boolean).join(' · ') + (c.spec.quirks.length ? ` · quirks: ${c.spec.quirks.join('; ')}` : '')));
        }) : [h('li', { class: 'empty' }, 'nothing yet')]));
      },
      every: 60_000, when: (e) => ['creation_made', 'creation'].includes(e.kind) || tool(e, 'tend'),
    };
  },
};

const gallery = {
  title: () => 'Pictures & writing', wide: true,
  build(card) {
    const box = h('div', { class: 'gallery' });
    card.append(box);
    return {
      async refresh() {
        const works = await api('/works?limit=60');
        box.replaceChildren(...(works.length ? works.map((w) => w.kind === 'drawing'
          ? h('figure', { class: 'work' }, h('a', { href: withAgent(`/works/${w.id}.png?width=1200`), target: '_blank', rel: 'noopener' },
              h('img', { src: withAgent(`/works/${w.id}.svg`), alt: w.title, loading: 'lazy' })),
            h('figcaption', {}, h('b', {}, `#${w.id} ${w.title}`), w.caption ? ` — ${w.caption}` : '', h('small', {}, fmtDay(w.ts))))
          : h('article', { class: 'work' }, h('h3', {}, `#${w.id} ${w.title}`), h('p', { class: 'poem' }, w.body), h('small', {}, fmtDay(w.ts))))
          : [h('p', { class: 'hint' }, 'Nothing drawn or written yet.')]));
      },
      when: (e) => e.kind === 'made_work',
    };
  },
};

// Proposals wait here for the owner; the public sees what is live.
const MODULE_ORDER = { waiting: 0, live: 1, disabled: 2, proposed: 3, rejected: 4, replaced: 5 };
const modules = {
  title: () => 'Modules', wide: true,
  build(card) {
    const box = h('div');
    card.append(h('p', { class: 'hint' }, `Features the world and ${ctx.name} write as code. New ones wait here for the owner's approval.`), box);
    const authors = () => ({ world: 'by the world', agent: `by ${ctx.name}`, library: 'shipped' });
    let refresh;
    const moduleCard = (m) => {
      const r = m.report || {};
      const list = (title, xs) => (xs && xs.length ? [h('b', {}, title), h('ul', { class: 'plain' }, ...[...new Set(xs)].slice(0, 6).map((x) => h('li', {}, x)))] : []);
      const decide = (what, ask) => async () => {
        const note = ask ? prompt(ask) : '';
        if (note === null) return;
        try { await post(`/modules/${m.id}/${what}`, { note }); } catch (e) { alert(e.message); }
        refresh();
      };
      const buttons = ctx.public ? [] : [
        ...(['waiting', 'disabled'].includes(m.status) ? [h('button', { type: 'button', onclick: decide('approve', 'Approve. A note for its author? (optional)') }, m.status === 'waiting' ? 'Approve' : 'Turn back on')] : []),
        ...(m.status === 'waiting' ? [h('button', { type: 'button', onclick: decide('reject', 'Reject. What should its author know?') }, 'Reject')] : []),
        ...(m.status === 'live' ? [h('button', { type: 'button', onclick: decide('disable', 'Switch it off. Why? (optional)') }, 'Switch off')] : []),
      ];
      const summary = r.calls !== undefined ? `Dry run: ${r.calls} calls, ${r.clean ? 'clean' : 'problems'}${r.slowest_ms ? `, slowest ${r.slowest_ms} ms` : ''}.` : '';
      return h('details', { class: `module ${m.status}`, open: m.status === 'waiting' },
        h('summary', {}, h('b', {}, m.name), ` v${m.version} · ${m.kind}${m.subject ? ` of ${m.subject}` : ''} · ${authors()[m.author] || `by ${m.author}`} `,
          h('span', { class: 'mstatus' }, m.status)),
        m.reason ? h('p', {}, m.reason) : null,
        m.offers && m.offers.length ? h('p', {}, h('b', {}, 'Actions: '), m.offers.map((o) => `${o.name} (${o.help})`).join('; ')) : null,
        m.note ? h('p', { class: 'hint' }, `Note: ${m.note}`) : null, summary ? h('p', {}, summary) : null,
        ...list('Errors', r.errors), ...list('Refused', r.refused), ...list(`Would tell ${ctx.name}`, r.perceived), ...list('Would log', r.logged), ...list('Replies', r.replies),
        buttons.length ? h('p', { class: 'actions' }, ...buttons) : null,
        m.source ? h('details', {}, h('summary', {}, 'Code'), h('pre', { class: 'code' }, m.source)) : null);
    };
    refresh = async () => {
      const rows = await api('/modules');
      rows.sort((a, b) => (MODULE_ORDER[a.status] ?? 9) - (MODULE_ORDER[b.status] ?? 9) || b.id - a.id);
      box.replaceChildren(...(rows.length ? rows.filter((m) => m.status !== 'replaced').map(moduleCard) : [h('p', { class: 'hint' }, 'No modules yet.')]));
    };
    return { refresh, when: (e) => ['module_live', 'module_disabled', 'module_rejected', 'builder'].includes(e.kind) };
  },
};

// The world's own doings: the builder's nights, modules going live, off or turned down, people brought, and modules whose calls fail.
const doings = {
  title: () => "The world's doings", wide: true, owner: true,
  build(card) {
    const failing = h('div'), list = h('ul', { class: 'plain doings' });
    card.append(failing, list);
    return {
      async refresh() {
        const d = await api('/world/doings');
        failing.replaceChildren(...section('Failing calls', d.failing.map((m) => h('li', { class: 'failing' },
          `${m.name} v${m.version}: ${m.fails} of its last ${m.calls} calls failed`, h('small', {}, `${fmtDay(m.last_ts)} · ${m.last}`)))));
        list.replaceChildren(...(d.happened.length ? d.happened.map((x) => h('li', {}, x.text, h('small', {}, `${fmtDay(x.ts)}${x.who !== ctx.name ? ` · seen by ${x.who}` : ''}`)))
          : [h('li', { class: 'empty' }, 'nothing yet')]));
      },
      every: 60_000, when: (e) => ['builder', 'module_live', 'module_disabled', 'module_rejected', 'character'].includes(e.kind),
    };
  },
};

// ---- mind (all from /memory) --------------------------------------------------------------------------------------------------------
const STAT_NAMES = { work_sessions: 'work sessions', minutes_worked: 'minutes worked', with_approach: 'with an approach stated',
  setbacks: 'setbacks', blowups: 'blow-ups', breakthroughs: 'breakthroughs', experiments: 'experiments', projects_finished: 'projects finished',
  visitor_messages: 'visitor messages', notes_written: 'journal entries', letters_sent: 'letters sent', hours_slept: 'hours slept',
  tool_errors: 'tool errors', predictions: 'predictions', surprises: 'surprises', focus_kept: 'focus kept', focus_total: 'focus reviewed' };
const mindWhen = (e) => ['reflection', 'night_pass', 'night_undo', 'woke'].includes(e.kind) || tool(e, 'undo_decision');
function mind(title, render) {
  return {
    title,
    build(card) {
      const box = h('div');
      card.append(box);
      return {
        async refresh() {
          const m = await read('/memory');
          box.replaceChildren(...(m.last_reflection_ts ? render(m) : [h('p', { class: 'hint' }, `${ctx.name} reflects each night; nothing yet.`)]));
        },
        every: 60_000, when: mindWhen,
      };
    },
  };
}
const hunch = (i) => (i.grounded ? null : h('span', { class: 'tag' }, 'hunch'));
const self = mind(() => `Who ${ctx.name} is`, (m) => [h('p', {}, m.self || ''),
  m.portraits && m.portraits.length > 1 ? h('p', { class: 'hint' }, `${m.portraits.length} versions of this portrait are kept.`) : null,
  ...section('Days that mattered', (m.turning || []).filter((t) => t.grounded).slice(0, 4).map((t) => h('li', {}, t.text, h('small', {}, fmtDay(t.period_end)))))]);
const beliefs = mind(() => 'Beliefs & change', (m) => [
  ...section('Beliefs', (m.insights || []).filter((i) => i.grounded).slice(0, 8).map((i) => h('li', {}, i.text, h('small', {}, `importance ${i.importance}${i.support && !['legacy', 'none'].includes(i.support) ? ` · ${i.support}` : ''}`)))),
  ...section('Hunches', (m.insights || []).filter((i) => !i.grounded).slice(0, 4).map((i) => h('li', {}, i.text, hunch(i)))),
  ...section(`How ${ctx.name} has changed`, (m.changes || []).slice(0, 4).map((c) => h('li', {}, c.text, hunch(c), h('small', {}, fmtDay(c.period_end)))))]);
const people = mind(() => 'People & days', (m) => {
  const ex = (m.expectations || []).filter((x) => x.kind !== 'step');
  return [...section('People', ctx.public ? [] : (m.people || []).map((p) => h('li', {}, h('b', {}, p.name), ` — ${p.notes}`))),
    ...section('Days', (m.days || []).slice(0, 5).map((d) => h('li', {}, d.text, h('small', {}, fmtDay(d.period_end))))),
    ex.length ? h('p', { class: 'hint' }, `${ex.length} predictions recorded, ${ex.filter((x) => x.surprising).length} surprising.`) : null];
});
const night = mind(() => 'Sleeping self', (m) => {
  const decisions = (m.night_decisions || []).slice(0, 6).map((d) => h('li', { class: d.undone ? 'done' : '' }, `#${d.id} ${d.summary}`,
    h('small', {}, [fmtDay(d.ts), d.undone ? 'undone' : d.applied ? 'applied' : 'logged only', d.reason].filter(Boolean).join(' · '))));
  const days = (m.stats || []).slice(-3).reverse().map((st) => h('li', {}, st.day, h('small', {},
    Object.entries(STAT_NAMES).filter(([k]) => st[k]).map(([k, label]) => `${st[k]} ${label}`).join(', ') || 'a quiet day')));
  return [...section('Decisions', decisions), ...section('Recent days in numbers', days),
    decisions.length || days.length ? null : h('p', { class: 'hint' }, `Nothing decided in ${ctx.their} sleep yet.`)];
});
const caps = mind(() => `What ${ctx.name} can do`, (m) => (m.capabilities ? Object.entries({ tool: 'Tools', craft: 'Crafts', ability: 'Abilities' }).flatMap(([g, title]) => {
  const top = Object.entries(m.capabilities[g] || {}).filter(([, c]) => c.tries >= 3).sort((x, y) => y[1].tries - x[1].tries).slice(0, 8);
  return top.length ? [h('h3', {}, title), h('div', { class: 'caps' }, ...top.map(([n, c]) => h('span', { class: 'chip', title: `${c.good} good, ${c.neutral} slow, ${c.bad} bad of ${c.tries}` }, `${n} ${c.good}/${c.tries}`)))] : [];
}) : [h('p', { class: 'hint' }, `Counted each night from what ${ctx.name} has actually done.`)]));

// ---- everyone (a world of several agents) -------------------------------------------------------------------------------------------
const glance = {
  title: () => 'Everyone', wide: true, owner: true,
  build(card) {
    const grid = h('div', { class: 'everyone' });
    card.append(grid);
    return {
      async refresh() {
        const all = await api('/world/agents');
        grid.replaceChildren(...all.map((a) => {
          const u = a.usage, doing = a.session?.label || [a.activity, a.description].filter(Boolean).join(' — ');
          return h('div', { class: 'someone' },
            h('h3', {}, h('a', { href: `?agent=${encodeURIComponent(a.key)}` }, a.name), ' ', h('small', {}, a.kind)),
            h('p', {}, h('b', {}, cap(a.place)), ` · ${doing}`), a.mood ? h('p', { class: 'hint' }, `feeling ${a.mood}`) : null,
            a.condition ? h('p', { class: 'failing' }, a.condition.outcome === 'knocked_out' ? 'knocked out' : `too weak (${a.condition.label})`) : null,
            ...a.stats.map((s) => bar(s.label, s.value, s.good === 'low' ? 'low-good' : '')),
            bar(`tokens today, ${(u.total_tokens / 1e3).toFixed(0)}k of ${(u.budget / 1e6).toFixed(1)}M`, u.budget ? u.total_tokens / u.budget : 0));
        }));
      },
      every: 10_000,
    };
  },
};

const between = {
  title: () => 'Between them', wide: true, owner: true,
  build(card) {
    const way = h('div'), list = h('ul', { class: 'plain between' });
    card.append(way, list);
    const line = (x) => (x.kind === 'met' ? `${x.who} and ${x.to} met${x.place ? ` at the ${x.place}` : ''}`
      : x.kind === 'said' ? `${x.who} to ${x.to}: “${x.text}”` : `${x.who} wrote to ${x.to}: ${x.text}${x.enclosed ? ` (tucked inside: ${x.enclosed})` : ''}`);
    return {
      async refresh() {
        const d = await api('/world/between');
        const now = Date.now() / 1000;
        way.replaceChildren(...section('In the post', d.on_the_way.map((l) => h('li', {}, `${l.who} → ${l.to}: ${l.text}`,
          h('small', {}, `arrives in ~${Math.max(1, Math.round((l.arrives - now) / 60))} min${l.enclosed ? ` · with ${l.enclosed}` : ''}`)))));
        list.replaceChildren(...(d.happened.length ? d.happened.map((x) => h('li', {}, line(x), h('small', {}, fmtDay(x.ts))))
          : [h('li', { class: 'empty' }, "They haven't met yet.")]));
      },
      every: 30_000,
    };
  },
};

export const PANELS = { feed, now: rightNow, lately, emotions, journal, map, belongings, standing, letters, give, projects, creations, gallery,
  modules, doings, self, beliefs, people, night, caps, everyone: glance, between };

// The engine's tabs, for a world whose pack doesn't choose its own (dashboard.json `tabs`). Everyone shows only with several agents.
export const TABS = [
  { key: 'now', title: 'Now', panels: ['feed', 'now', 'lately', 'emotions'] },
  { key: 'everyone', title: 'Everyone', panels: ['everyone', 'between'], several: true },
  { key: 'journal', title: 'Journal', panels: ['journal'] },
  { key: 'world', title: 'World', panels: ['map', 'belongings', 'standing', 'letters', 'give'] },
  { key: 'work', title: 'Work', panels: ['projects', 'creations', 'gallery', 'modules', 'doings'] },
  { key: 'mind', title: 'Mind', panels: ['self', 'beliefs', 'people', 'night', 'caps'] },
];
