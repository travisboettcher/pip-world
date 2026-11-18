// Chat with the agent: a bubble at the bottom right (a sheet on phones), its unread count, and a "thinking" line while a message waits.
import { $, ctx, h, fmtTime, post, store } from './core.js';

const TYPING_TIMEOUT_MS = 150_000;
const SILENT_AFTER_READ_MS = 8_000;
const chat = { seenInbox: new Set(), pending: new Map(), typing: null, open: false, unread: 0 };

function renderBadge() {
  $('chat-badge').hidden = chat.unread === 0;
  $('chat-badge').textContent = String(chat.unread);
  $('chat-toggle').setAttribute('aria-label', chat.unread ? `Chat (${chat.unread} unread)` : 'Chat');
}
export function setChatOpen(on, focus = true) {
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
export const chatOpen = () => chat.open;
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
    chat.typing = h('div', { class: 'msg agent typing', 'aria-label': `${ctx.name} is thinking` }, `${ctx.name} is thinking`);
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
export function trackPending(id) {
  const timer = setTimeout(() => {
    if (!chat.pending.has(id)) return;
    chat.pending.delete(id);
    bubble('sys', `No answer yet — ${ctx.name} may be busy or paused. Your message is still queued.`);
    syncTyping();
  }, TYPING_TIMEOUT_MS);
  chat.pending.set(id, { timer });
  syncTyping();
}
export const seen = (id) => chat.seenInbox.add(id);       // a gift is shown as its own line, not as a visitor's message
function showVisitor(id, text, ts, via) {
  if (chat.seenInbox.has(id)) return false;
  chat.seenInbox.add(id);
  bubble('you', text, ts, via);
  return true;
}
export function chatFromEvent(e, live) {
  const d = e.data || {};
  if (e.kind === 'inbox' && !d.gift && !d.letter && d.source !== 'agent') {
    if (showVisitor(d.id, d.text, e.ts, d.source) && live && d.source && d.source !== 'web' && !chat.open) { chat.unread += 1; renderBadge(); }
  } else if (e.kind === 'gift') bubble('sys', `${d.sender} gave ${ctx.name} ${d.qty} × ${d.item}`);
  else if (e.kind === 'say' && !d.to_name) {
    if (d.text) {
      bubble('agent', d.text, e.ts);
      if (live && !chat.open) { chat.unread += 1; renderBadge(); }
    } else if (live) bubble('sys', `${ctx.name} says nothing.`);
    for (const id of d.to || []) settle(id);
    syncTyping();
  } else if (e.kind === 'inbox_read' && live) {
    for (const id of d.ids || []) {
      const p = chat.pending.get(id);
      if (!p) continue;
      clearTimeout(p.timer);
      p.timer = setTimeout(() => {
        if (!chat.pending.delete(id)) return;
        bubble('sys', `${ctx.name} read your message but chose not to say anything.`);
        syncTyping();
      }, SILENT_AFTER_READ_MS);
    }
  }
}

export function setUpChat() {
  $('chat-title').textContent = `Chat with ${ctx.name}`;
  $('chat-input').placeholder = `Say something to ${ctx.name}…`;
  $('chat-panel').setAttribute('aria-label', `Chat with ${ctx.name}`);
  $('chat-toggle').addEventListener('click', () => setChatOpen(!chat.open));
  $('chat-close').addEventListener('click', () => { setChatOpen(false); $('chat-toggle').focus(); });
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
}
