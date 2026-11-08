# Design: conversation

Status (2026-11-07): **part 1 built (0.8.1)**; part 2 (the conversation scene) to be designed. Prompted by the owner: Pip's talk with Oriel "does not read very
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

## Part 2 (to be designed): the conversation scene
For in-person talk (neighbors, residents, creations with a mind): the visit runs as its own short scene, with a small focused prompt for Pip's turns (its persona, why it
came, a few facts, the transcript, and only say / hand over / feel / take its leave), the other side's turn as now, alternating at conversational speed until either says
goodbye or about six exchanges, then one summary into memory for Pip's world turn. Chats with the owner stay in the world turn (they often call for action), with the
transcript from part 1. Neighbor letters get the repeat check and their own recent letters verbatim (the "palm on the step" motif), from DESIGN-neighbor-memory.md.
