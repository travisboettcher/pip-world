# Design: long-term memory

Status (2026-10-29): steps 0-2 built and tested (unit tests, a real reflection over a snapshot of live Pip's
history, and a live tick where Pip used `recall` unprompted); not yet deployed. Steps 3-4 designed only.

## Problem
Pip's only memory is its prompt. Every tick it sees the last 4 diary entries, the last 15 events and up to 10 open
items per journal list. After three hours of running (627 events, 40 diary entries) everything older than about an
hour is invisible: its first projects, how it felt about its first gift, why Morgan matters to it. There is no
sense of *days*, no beliefs that outlast the diary window, and no way to look anything up.

Goal: continuity across days at a **fixed prompt cost**, in Pip's own voice, plus a way to deliberately remember.

## Model
Borrowed loosely from Generative Agents (Park et al., 2023) and ordinary psychology:

| Kind | What | Where | In the prompt |
|---|---|---|---|
| Working | the current situation | perception | always |
| Episodic | what happened | `events`, diary, and nightly **day summaries** | latest few days; the rest via recall |
| Semantic | beliefs, lessons, facts | nightly **insights** (with importance), `learned` notes | the most important few |
| Social | who people are to Pip | **people notes**, one per person | people Pip knows, most recent first |
| Identity | who Pip is | a short **self-portrait** | always |
| Procedural | getting better at things | skill xp (projects) | already built |

Four mechanisms: **writing** (exists), **consolidation** (step 1), **retrieval** (steps 2-3), **forgetting** (step 4).

## Step 0: who's talking (prerequisite)
Visitor messages are anonymous text, so nothing can be remembered about a person. The inbox gets a `sender` column
(default "A visitor"); `POST /inbox` takes an optional `sender`; `pipchat` sends `--from` (default `$PIP_NAME`, else
"Morgan", matching `give`); the web UI sends the name already remembered for gifts. Perception shows
`- Morgan: hello` instead of `- hello`, and `inbox` events carry the sender so reflection and recall see it.

## Step 1: sleep (nightly reflection)
Once a day, after `REFLECT_HOUR` local time (default 3 am), the monitor runs one reflection for everything since the
last one (the first run covers everything so far). Manual trigger: `POST /reflect`, `pipchat reflect`.

**Pip reflects, not the GM**: it is Pip's identity, so the call uses Pip's persona as the system prompt (same
backend and budget), framed as "you are asleep, going over your day", with one structured `report` tool.

Input:
- its current self-portrait and people notes
- the period's material, condensed to one line each, newest kept if over budget (~12k chars): diary entries,
  visitor messages (with sender) and Pip's replies, gifts, work results, things made, crossed-off notes, things
  learned, companion lines

Output (all first person, validated and clipped by the engine):
- `summary`: 2-4 sentences, the day as Pip will remember it
- `insights`: 0-5 `{text, importance 1-10}`: lessons and beliefs about itself, its work, the world, others
- `people`: updated notes (1-3 sentences) for anyone who mattered in the period; others are kept unchanged
- `self`: the revised self-portrait (<= 120 words), written fresh each night from the old one plus the day

Storage: table `reflections` (kind `day` | `insight`, text, importance, period start/end), table `people`
(name, notes, first/last seen), self-portrait in `meta`. A `reflection` event is logged.

Failure: nothing is marked done; it retries after an hour (`gm_error`-style `reflection_error` event).

**In the prompt** (bounded, roughly 600-900 tokens however long Pip lives):
- `Who you are (in your own words)`: the self-portrait
- `People you know`: up to 5 people, most recently seen first
- `Recent days`: the last 3 day summaries
- `Things you've come to believe`: the 5 most important insights (recency breaks ties)

The existing "last 4 diary entries" stays: it's today's raw memory; the reflections are everything before.

## Step 2: `recall(query)`
A tool that lets Pip search its own past on purpose ("what did Morgan say about the clock?").

- One FTS5 table `recall_index(text, source, ref, ts)` holds everything worth remembering: journal notes (all
  sections and statuses), day summaries and insights, people notes, and events of kinds `inbox` (with sender),
  `say`, `gift`, `work`, `creation_made`, `companion`. Rows are added when written (`State.log`, `add_memory`,
  reflection), edits replace the row, and existing data is backfilled once on startup.
- The query is reduced to plain words (stop words dropped, prefix-matched, OR-ed) and ranked by BM25; the best 5
  come back oldest-first with a relative time ("3 days ago (diary): ...").
- Results are a follow-up, so Pip can act on them in the same wake. Nothing found is an answer too.

## Step 3 (built 0.10.0): "this reminds you of..."
Each tick, build a query from the situation (visitor's words and name, active project, creation in view) and put the
top 2-3 recall hits in the prompt, scored recency x importance x relevance, within a fixed token budget. The full design,
with context per memory, activation and fading, and a logged competition: [DESIGN-reminders.md](DESIGN-reminders.md).

## Step 4 (designed, not built): forgetting
Raw events older than a few days stop being indexed individually once a day summary covers them; insights that are
never recalled slowly lose rank. Nothing is deleted from the database. Memories can drift: a summary is a
reconstruction, so Pip may misremember a little, which is a feature.

## Findings from the first real run
On a snapshot of live Pip (627 events, 3.5 hours): the reflection picked out what mattered (deciding "close
enough" instead of re-checking forever; Morgan's gifts making the work feel shared), wrote a coherent self-portrait
and a note on Morgan; the memory section came to ~490 tokens. Asked "do you remember the first thing I gave you?",
Pip called `recall` on its own and answered correctly from 3 hours back.

Known limits, deliberately left for steps 3-4:
- A reflection reads only the newest ~12k chars (`REFLECT_MAX_CHARS`), so the very first one dropped Pip's first
  hour. Recall still finds it; nightly reflections cover a day, which fits.
- Prefix matching is a little noisy ("give" also matches "gives"). Embeddings (step 3) would fix it.
- Old diary entries from before the stat-number guard still contain "hunger 0.22"-style text, and recall surfaces it.

## Cost
One reflection a day (~10-15k input tokens, ~1k output). Recall costs nothing but the follow-up call. The memory
section of the prompt adds ~600-900 tokens per tick once it's full.
