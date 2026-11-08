# Design: conversation

Status (2026-11-07): **part 1 built (0.8.1)**; **part 2 built (0.9.0)**. Prompted by the owner: Pip's talk with Oriel "does not read very
naturally", and Pip misread a reply to a postcard it did not know it had sent.

## What was wrong (measured over all 149 lines Oriel and Pip had exchanged)
- Oriel: an `*action*` in 60 of 60 lines, her palm, the tin or the step in 43, a question in 1. Her prompt said "a small action in *asterisks* is fine", which reads as
  "always", and her persona is all touch, so every action was the same one; and she was asked to answer Pip, so she instructed.
- Pip: "Thank you, Oriel." to open 53 of 89 lines, then her instruction said back to her; once the same line twice running. Pip talks from inside its full world turn (about
  13k tokens and thirty tools), where her last line is one item among the garden and the clock, and nothing shows it the conversation as a whole.
- Chats with the owner have the same shape: the new message is one inbox line, and the rest of the thread only survives as stray "recent events". Pip did not know the
  wish postcard it was replying about was its own.

## Part 1 (0.8.1): the same few rules for every conversation
- **No saying the same thing twice** (`conversation.repeats`): a run of six words in common with a recent line, or (for a line of five words or more) nearly the same line,
  stage directions left out. Pip's `say` is turned down with "you said that a moment ago" (two hours back); a neighbor who repeats one of her last eight lines is asked once
  more, told her first try repeated itself.
- **The conversation shown whole.** At a neighbor's home Pip sees "Talking with Oriel (this visit)" with both sides verbatim. With a visitor waiting, Pip sees "Your
  conversation with Travis so far": their messages, its answers, and the postcards it sent on that channel (marked as its own). Its postcards also appear among its
  recent events.
- **Talk like a person.** The neighbor and resident prompts now ask for one or two sentences, actions only when they help and never one already used, and allow
  asking, telling her own news or opinion, disagreeing and closing the talk, rather than instructing or restating. A creation with a mind is told not to repeat the
  conversation. Pip has a guideline: answer what was just said, don't open with thanks or say back what you were told, ask something back, and say goodbye before
  walking away.
- **The day and time** are in Pip's prompt, so "Thursday at half past four" can be kept.

## Part 2 (0.9.0): the conversation scene
The plan was: for in-person talk the visit runs as its own short scene, with a small focused prompt for Pip's turns, the other side's turn as now, alternating at
conversational speed until either says goodbye or about six exchanges, then Pip's world turn picks up. Chats with the owner stay in the world turn (they often call for
action). Neighbor letters get the repeat check. What was built (`app/talk.py`, `Agent._converse`, `tests/test_talk.py`):

- **When.** At the start of a world turn, if someone Pip is with in person (a neighbor at home, a resident at their place) has spoken since Pip arrived, this visit has
  not had its talk yet, and no visitor is waiting in the inbox (a visitor's message comes first; the talk waits), the turn becomes a talk. `TALK_SCENES=off` turns it off.
- **Pip's turn** gets its persona, "you are face to face with Marigold", and a prompt of about 1.5k characters: the date and time, where it is and with whom, its own
  notes about them, up to three open to-dos that mention them, what it was doing and its mood, what it carries (eight items) and its coins, the visit's talk verbatim, and
  "answer what was just said; don't open with thanks; say goodbye when it has run its course". Only `say` (with `goodbye`) and `feel` are offered. Each turn is a logged
  `tick` with reason `talk` and counts toward the daily token budget.
- **Her turn** is the same in-person reply as before (`neighbors.reply`, with its repeat retry), asked at once, and told she may close the talk (`goodbye`).
- **It ends** when Pip says goodbye (her parting line still comes), she says goodbye, Pip's turn says nothing, she has nothing to say, the budget is spent, or after six of
  Pip's lines. It is logged as a `talk` event (`name`, `turns`, `ended`), the visit is marked as talked (`talk_done`), and the world turn runs next with the whole
  transcript in view, free to give, trade, note or leave. A `say` with `goodbye` in the world turn also ends the visit's talk, so a second scene does not start.
- **While it runs** the monitor leaves her answers to the scene (`talk_scene` meta), so no line is answered twice.
- Deviations: no separate summary into memory (the world turn sees the transcript and Pip notes what it wants); handing things over and leaving stay in the world turn
  rather than in the scene's tools; creations with a mind are not in scenes yet (they answer in Pip's world turn as before).

**Letters.** A neighbor's letter that repeats one of her last six (`LETTERS_CHECKED`) is written once more, told "your first try repeated an earlier letter; write it
afresh", and every letter prompt asks her not to reuse a sentence, image or daily ritual from earlier letters.

**Free time.** At home, awake, with nothing ripe, no visitor waiting and nothing due (a crop or a creation that needs tending) for two hours or more, Pip's prompt says
"Nothing needs you for about N hours." with its open ambitions and its wishes to do (two of each) and that `start_project` begins something new. Facts, not orders.
