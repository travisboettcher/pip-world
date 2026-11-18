// The activity feed: every event the agent's log has, in a line each (the engine's kinds, and a module's own event as it says it reads).
import { ctx, h, fmtTime, store } from './core.js';

const GROUPS = [['chat', 'Chat'], ['actions', 'Actions'], ['journal', 'Journal'], ['world', 'World'], ['recall', 'Recall'], ['system', 'System']];

function describeTool(d) {
  const a = d.args || {}, r = String(d.result ?? ''), N = ctx.name;
  if (ctx.public) return d.result ? { group: 'actions', text: `${N}: ${r}` } : null; // the public feed carries results, not arguments
  if (d.noop) return null; // nothing changed (e.g. restating the same activity)
  switch (d.tool) {
    case 'say': return null; // shown via the 'say' event
    case 'set_activity': return { group: 'actions', text: `${N} is now ${a.activity}` + (a.description ? ` — ${a.description}` : '') };
    case 'note_to_self': {
      const sec = a.section || 'diary';
      if (r.startsWith('not written')) return { group: 'system', cls: 'warn', text: `${N}'s ${sec} note was refused: ${r.replace('not written: ', '')}` };
      return { group: 'journal', text: `${N} writes in ${ctx.their} ${sec}: ${a.text}` };
    }
    case 'edit_note':
      if (r.startsWith('error') || r.startsWith('not edited')) return { group: 'system', cls: 'warn', text: `${N} couldn't edit #${a.id}: ${r}` };
      return { group: 'journal', text: `${N} rewrites #${a.id}: ${a.text}` };
    case 'resolve_note': return { group: 'journal', text: `${N} crosses off #${a.id}` + (a.outcome ? `: ${a.outcome}` : '') };
    case 'use_item': return { group: 'world', cls: 'world', text: `${N} uses ${a.item}` + (a.purpose ? ` — ${a.purpose}` : '') };
    case 'sleep': return { group: 'actions', text: r.startsWith('you go to bed') ? `${N} goes to bed` : `${N} can't sleep yet: ${r}` };
    case 'gather': return { group: 'actions', text: r.startsWith('you set about') ? `${N} ${r.replace(/^you /, '')}`.replace(/ You'll see.*$/, '') : `${N} can't gather: ${r}` };
    case 'undo_decision': return { group: 'journal', text: `${N} takes back a night decision: ${r}` };
    case 'settle': return null; // shown via the 'settled' event
    case 'eat': return { group: 'actions', text: a.item ? `${N} eats ${a.item}` : `${N} has a meal` };
    case 'rest': return { group: 'actions', text: `${N} rests` };
    case 'web_search': return { group: 'actions', text: `${N} searches the web for: ${a.query}` };
    case 'go_to': return /^(error|can't)/.test(r) ? { group: 'system', cls: 'warn', text: `${N} can't go: ${r}` } : { group: 'actions', text: `${N} sets off for ${a.place}` };
    case 'tend': return { group: 'world', cls: 'world', text: `${N} ${r}` };
    default: {
      if (/^error/.test(r)) return { group: 'system', cls: 'warn', text: `${N} tried ${d.tool}: ${r}` };
      return { group: 'actions', text: d.module && r ? `${N}: ${r}` : `${N} uses ${d.tool}` };
    }
  }
}

export function describe(e) {
  const d = e.data || {}, N = ctx.name;
  switch (e.kind) {
    case 'say': return d.to_name ? { group: 'world', cls: 'world', text: `${N} to ${d.to_name}: ${d.text}` }
      : { group: 'chat', text: `${N}: ${d.text || '(says nothing)'}` };
    case 'met': return { group: 'world', cls: 'world', text: `${N} meets ${d.name} (${d.about}) for the first time` };
    case 'gathered': return { group: 'world', cls: 'world', text: d.text + (d.interrupted ? ' (cut short)' : '') };
    case 'woke': return { group: 'world', cls: 'world', text: `${N} wakes after about ${d.hours} hours of sleep` + (d.early ? ' (woken early)' : '') };
    case 'made_work': return { group: 'world', cls: 'world', text: d.what === 'drawing' ? `${N} drew “${d.title}”${d.caption ? ` — ${d.caption}` : ''}` : `${N} wrote “${d.title}”` };
    case 'world_changed': return { group: 'world', cls: 'world', text: d.text };
    case 'stakes': return { group: 'world', cls: 'warn', text: d.outcome === 'knocked_out' ? `${N}'s ${d.label} ran out: knocked out, comes to at home in ${d.hours} hours` : `${N}'s ${d.label} ran out: too weak to do much until it recovers` };
    case 'recovered': return { group: 'world', cls: 'world', text: d.outcome === 'knocked_out' ? `${N} comes to` : `${N}'s ${d.label} recovers` };
    case 'night_pass': {
      const bits = [...(d.decisions || []), ...(d.focus || []).map((f) => `focus: ${f}`)];
      if (!bits.length) return d.failed ? { group: 'system', cls: 'warn', text: 'The night pass failed' } : null;
      return { group: 'journal', text: `${N}'s sleeping self${d.mode === 'log' ? ' (logged only)' : ''}: ${bits.join('; ')}` };
    }
    case 'night_undo': return { group: 'journal', text: `Night decision #${d.decision} taken back: ${d.summary}` };
    case 'creation_made': return { group: 'world', cls: 'world', text: `${N} made ${d.name} (${[d.quality, ...(d.capabilities || [])].filter(Boolean).join(', ')}): ${d.description}` };
    case 'creation': return { group: 'world', cls: d.what === 'stopped' ? 'warn' : 'world', text: ['stopped', 'helper', 'used'].includes(d.what) ? d.text : `${d.name}: ${d.text}` };
    case 'companion': return { group: 'world', cls: 'world', text: `${d.name}: “${d.text}”` };
    case 'module': return { group: 'world', cls: 'world', text: d.text };
    case 'builder': return { group: 'system', text: { proposed: `The world proposed a module: ${d.name}${d.revised ? ' (a new version)' : ''}`, nothing: `The world added nothing tonight${d.why ? `: ${d.why}` : ''}`,
      dropped: `The world dropped an idea (${d.name}): ${d.why}`, failed: `The world's builder couldn't propose anything: ${d.why}` }[d.outcome] || `Builder: ${d.outcome}` };
    case 'module_live': return { group: 'system', text: `Module ${d.name} (v${d.version}, ${d.author === 'world' ? 'by the world' : d.author === 'library' ? 'shipped' : `by ${N}`}) is live` };
    case 'module_disabled': return { group: 'system', cls: 'warn', text: `Module ${d.name} was switched off${d.why ? `: ${d.why}` : ''}` };
    case 'module_rejected': return { group: 'system', text: `Module ${d.name} v${d.version} was turned down${d.note ? `: ${d.note}` : ''}` };
    case 'talk': return { group: 'world', cls: 'world', text: `${N} and ${d.name} talked (${d.turns} turn${d.turns === 1 ? '' : 's'}; ${['agent', N].includes(d.ended) ? `${N} said goodbye`
      : d.ended === d.name ? `${d.name} said goodbye` : { silence: 'it trailed off', turns: 'talked out', budget: 'out of tokens', parted: 'one of them left' }[d.ended] || d.ended})` };
    case 'reflection': return { group: 'journal', text: `${N} slept on it: ${d.summary}` };
    case 'reflection_error': return { group: 'system', cls: 'warn', text: `${N}'s nightly reflection failed; it'll retry in an hour` };
    case 'inbox': return d.letter ? { group: 'world', cls: 'world', text: d.text }
      : d.gift ? null : { group: 'chat', text: `${d.sender || 'Visitor'}${d.source && d.source !== 'web' ? ` (via ${d.source})` : ''}: ${d.text}` };
    case 'outreach': {
      const to = d.what === 'postcard' ? 'sent a postcard' : 'answered';
      if (!d.delivered) return { group: 'system', cls: 'warn', text: `${N} tried to send a ${d.what === 'postcard' ? 'postcard' : 'reply'} via ${d.channel} but it didn't go: ${d.error || d.status}` };
      return { group: 'world', cls: 'world', text: `${N} ${to} via ${d.channel}${d.mode === 'log' ? ' (logged only)' : ''}: ${d.text}` };
    }
    case 'arrived': return { group: 'world', cls: 'world', text: d.place === ctx.home ? `${N} gets home` : `${N} arrives at ${d.label || d.place}` + (d.first_time && d.description ? ` — ${d.description}` : '') };
    case 'reading': return { group: 'world', cls: 'world', text: `${N} reads ${d.title}${d.finished ? ' (finished!)' : ` (${d.percent}%)`}: ${d.summary}` };
    case 'letter_sent': return { group: 'world', cls: 'world', text: `${N} wrote to ${d.to}: ${d.text}` + (d.enclosed ? ` (enclosed: ${d.enclosed})` : '') };
    case 'character': return { group: 'world', cls: 'world', text: `Someone new (${d.role}): ${d.name} — ${d.about}` };
    case 'gift': return { group: 'world', cls: 'world', text: `${d.sender} gave ${N} ${d.qty} × ${d.item}` };
    case 'stall_sale': return { group: 'world', cls: 'world', text: `${N} sold ${d.qty} ${d.item} at ${ctx.their} stall for ${d.coins} coin${d.coins === 1 ? '' : 's'}${d.left ? ` (${d.left} left)` : ' (sold out)'}` };
    case 'happening': return { group: 'world', cls: d.tone === 'bad' ? 'warn' : 'world', text: `Something happened — ${d.title}: ${d.text}${d.effects ? ` ${d.effects}` : ''}` };
    case 'reminded': return d.shown && d.shown.length ? { group: 'recall', text: `On ${N}'s mind: ${d.shown.map((m) => m.text).join(' · ')}` } : null;
    case 'faded': return { group: 'journal', text: `${d.count} old memor${d.count === 1 ? 'y' : 'ies'} faded (recall can still find ${d.count === 1 ? 'it' : 'them'})` };
    case 'wares': return { group: 'world', cls: 'world', text: `${d.name} has things for sale: ${d.wares.join(', ')}` };
    case 'offered': return { group: 'system', text: `${d.name}'s next letter may offer ${d.item} (${d.price} coins${d.wished ? `, something ${N} wished for` : ''})` };
    case 'sold_creation': return { group: 'world', cls: 'world', text: `${N} sold ${d.name} at ${d.place} for ${d.coins} coin${d.coins === 1 ? '' : 's'}` };
    case 'wished': return { group: 'journal', text: `${N} wishes (${d.wish}): ${d.text}` };
    case 'happening_felt': return { group: 'journal', text: `${N} took “${d.title}” as ${d.read_as}${d.read_as === d.lens ? '' : ` (it was written as ${d.lens})`}` };
    case 'emotion': return { group: 'world', cls: 'world', text: `${N}'s ${d.emotion} is high (${d.value}): ${d.cause}` };
    case 'settled': return { group: 'actions', text: `${N} settles ${ctx.their} ${d.emotion} (${d.from} → ${d.to})` + (d.how ? `: ${d.how}` : '') };
    case 'alert': return { group: 'world', cls: 'warn', text: `${N}'s ${d.stat} needs attention` };
    case 'budget_exceeded': return { group: 'world', cls: 'bad', text: `${N} has used today's token budget and is asleep until tomorrow.` };
    case 'error': return { group: 'system', cls: 'bad', text: String(d.error) };
    case 'tool_error': return { group: 'system', cls: 'warn', text: `tool ${d.tool} failed: ${d.error}` };
    case 'tick': return { group: 'system', cls: 'system', text: `tick (${d.reason}, step ${d.step ?? 0}, ${d.tokens} tokens)` + (d.text ? `: ${d.text}` : '') };
    case 'inbox_read': return { group: 'system', cls: 'system', text: `${N} read message(s) ${(d.ids || []).join(', ')}` };
    case 'start': return { group: 'system', cls: 'system', text: `started: ${d.model} via ${d.backend}, pacing ${d.pacing}` };
    case 'tool': return describeTool(d);
    default: {                                                    // a module's own event, as it says it reads (public: just its line)
      const line = d.by && (d.text || d.read?.public || d.read?.line);
      return line ? { group: 'world', cls: 'world', text: line } : null;
    }
  }
}

// The Activity card: the feed with its filters. Events arrive through on(); the newest go on top.
export const feed = {
  title: () => 'Activity', wide: true,
  build(card) {
    const filters = { chat: true, actions: true, journal: true, world: true, recall: false, system: false, ...store.get('filters', {}) };
    const chips = h('div', { class: 'filters', role: 'group', 'aria-label': 'Event filters' }), list = h('ol', { class: 'feed' });
    const apply = () => { for (const li of list.children) li.hidden = !filters[li.dataset.group]; };
    const renderChips = () => chips.replaceChildren(...GROUPS.filter(([key]) => !(ctx.public && key === 'chat')).map(([key, label]) => h('button', {
      type: 'button', class: 'chip', 'aria-pressed': String(!!filters[key]),
      onclick: () => { filters[key] = !filters[key]; store.set('filters', filters); renderChips(); apply(); },
    }, label)));
    renderChips();
    card.append(chips, list);
    return {
      on(e) {
        const m = describe(e);
        if (!m) return;
        const firsts = (e.data?.firsts || []).map((f) => f.label);
        const li = h('li', { 'data-group': m.group, class: m.cls || '' }, h('time', {}, fmtTime(e.ts)),
          h('span', {}, m.text, firsts.length ? h('span', { class: 'first' }, `★ ${firsts.join('; ')}`) : null));
        li.hidden = !filters[m.group];
        list.prepend(li);
        while (list.children.length > 400) list.lastChild.remove();
      },
    };
  },
};
